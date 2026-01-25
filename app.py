import shutil # [NEW] 파일 이동을 위한 도구 추가 (맨 위 import 쪽에 추가해주세요!)
import streamlit as st
import time
from streamlit_drawable_canvas import st_canvas
import os
from datetime import datetime
from io import BytesIO
from PIL import Image

# --- 기초 설정 및 폴더 생성 ---
st.set_page_config(page_title="나만의 AI 필기 노트", layout="centered")

# 저장소 폴더가 없으면 만듭니다
if not os.path.exists('user_data_local'):
    os.makedirs('user_data_local')
if not os.path.exists('user_data_cloud'):
    os.makedirs('user_data_cloud')

# --- [NEW] 데이터 반출 기능이 추가된 최종 관리자 대시보드 ---
def run_admin_dashboard():
    st.title("👨‍💻 데이터 품질 관리 센터 (QC)")
    st.caption("안전 모드: 삭제 시 휴지통으로 이동합니다.")
    
    # 사이드바에 데이터 내보내기 버튼 배치
    with st.sidebar:
        st.header("📦 데이터 반출")
        st.info("검수가 완료된 '승인' 데이터만 압축해서 다운로드합니다.")
        
        # 승인된 파일이 있는지 확인
        if os.path.exists('dataset_verified') and len(os.listdir('dataset_verified')) > 0:
            # 1. 압축 파일 만들기 (shutil 활용)
            # 'dataset_verified' 폴더 내용을 'my_dataset.zip'으로 압축
            shutil.make_archive('my_dataset', 'zip', 'dataset_verified')
            
            # 2. 다운로드 버튼 생성
            with open('my_dataset.zip', 'rb') as f:
                st.download_button(
                    label="📥 데이터셋 다운로드 (.zip)",
                    data=f,
                    file_name="goodnotes_dataset.zip", # 다운로드될 파일 이름
                    mime="application/zip",
                    use_container_width=True,
                    type="primary"
                )
        else:
            st.warning("다운로드할 승인 데이터가 없습니다.")

    st.markdown("---")
    
    # 1. 폴더 관리
    if not os.path.exists('dataset_verified'): os.makedirs('dataset_verified')
    if not os.path.exists('dataset_trash'): os.makedirs('dataset_trash')
        
    # 파일 현황 파악
    pending_files = [f for f in os.listdir('user_data_local') if f.endswith('.png')]
    verified_files = [f for f in os.listdir('dataset_verified') if f.endswith('.png')]
    trash_files = [f for f in os.listdir('dataset_trash') if f.endswith('.png')]
    
    # 2. 현황판
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("대기 중", f"{len(pending_files)}건", delta="검수 필요", delta_color="inverse")
    col2.metric("승인됨", f"{len(verified_files)}건", delta="AI 학습용")
    col3.metric("휴지통", f"{len(trash_files)}건", delta="삭제됨", delta_color="off")
    col4.metric("총 자산", f"{len(pending_files) + len(verified_files)}건")
    
    st.write("")
    st.subheader("🔍 데이터 검수 작업")
    
    if len(pending_files) == 0:
        st.success("🎉 현재 대기 중인 데이터가 없습니다.")
        # 휴지통 비우기 버튼
        if len(trash_files) > 0:
            with st.expander(f"🗑️ 휴지통 비우기 ({len(trash_files)}건)"):
                if st.button("영구 삭제 실행", type="primary"):
                    for f in trash_files:
                        try: os.remove(os.path.join('dataset_trash', f))
                        except: pass
                    st.toast("휴지통을 비웠습니다!")
                    time.sleep(1)
                    st.rerun()
        return

    # 3. 검수 인터페이스
    for idx, filename in enumerate(pending_files):
        file_path = os.path.join('user_data_local', filename)
        
        if idx % 3 == 0: cols = st.columns(3)
        
        with cols[idx % 3]:
            try:
                img = Image.open(file_path)
                st.image(img, use_container_width=True)
                st.caption(f"📄 {filename}")
                
                b_col1, b_col2 = st.columns(2)
                
                if b_col1.button("✅ 승인", key=f"ok_{filename}", use_container_width=True):
                    shutil.move(file_path, os.path.join('dataset_verified', filename))
                    st.toast(f"승인 완료! ({filename})")
                    time.sleep(0.5)
                    st.rerun()
                    
                if b_col2.button("🗑 삭제", key=f"del_{filename}", use_container_width=True):
                    shutil.move(file_path, os.path.join('dataset_trash', filename))
                    st.toast(f"휴지통으로 이동됨 ({filename})")
                    time.sleep(0.5)
                    st.rerun()
                    
            except Exception as e:
                st.error("파일 에러")

    st.markdown("---")
    with st.expander("📂 승인된 데이터 목록"):
        st.write(verified_files)


# --- 상태 관리 변수 초기화 ---
if 'step' not in st.session_state: st.session_state.step = 'WELCOME'
if 'accuracy' not in st.session_state: st.session_state.accuracy = 70
if 'tutorial_idx' not in st.session_state: st.session_state.tutorial_idx = 0
if 'storage' not in st.session_state: st.session_state.storage = 'Local'

pangrams = [
    "다람쥐 헌 쳇바퀴에 타고파", "닭 콩팥 훔친 집사", "물컵 속 팥 찾던 형",
    "동틀 녘 햇빛 포개짐", "자동차 바퀴 틈새가 파랗니", "해태 옆 치킨집 닭맛",
    "코털 팽 대감네 첩 좋소", "닭 잡아서 치킨파티 함", "초코볼은 티피가 맛 좋다"
]

# 가이드라인(그리드) 생성 함수 (벡터 방식)
def create_grid_drawing(text, width=1000, height=200):
    if len(text) == 0: return None
    step_x = width / len(text)
    objects = []
    for i in range(1, len(text)):
        x = i * step_x
        line = {
            "type": "line", "x1": x, "y1": 20, "x2": x, "y2": height - 20,
            "stroke": "#cccccc", "strokeWidth": 2, "selectable": False
        }
        objects.append(line)
    return {"version": "4.4.0", "objects": objects}

# 이미지 저장 함수
def save_handwriting_image(image_data, text, storage_type):
    if image_data is None: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_text = text.replace(" ", "_") 
    filename = f"{timestamp}_{safe_text}.png"
    
    if storage_type == 'Local':
        save_path = os.path.join('user_data_local', filename)
    else:
        save_path = os.path.join('user_data_cloud', filename)
    
    with open(save_path, "wb") as f:
        f.write(image_data)
    return filename, save_path

# =========================================================
# [핵심] 사이드바 설정 및 화면 분기
# =========================================================
with st.sidebar:
    st.header("⚙️ 설정")
    # 관리자 모드 체크박스
    is_admin = st.checkbox("관리자 모드 (Admin)", value=False)
    
    st.markdown("---")
    st.info("개발 버전: v0.3.0\nTarget: Goodnotes Exit")

# 관리자 모드가 켜져 있으면 -> 대시보드 실행하고 여기서 멈춤 (아래 코드 실행 안 함)
if is_admin:
    run_admin_dashboard()
    st.stop() # 중요: 여기서 앱 실행을 중단시켜서 일반 화면을 숨깁니다.

# =========================================================
# 아래부터는 기존 일반 사용자용 화면 (Normal User Flow)
# =========================================================

# --- 1. 환영 화면 ---
if st.session_state.step == 'WELCOME':
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>✍️ 환영합니다</h1>", unsafe_allow_html=True)
    time.sleep(2)
    st.session_state.step = 'ASK_LEARN'
    st.rerun()

# --- 2. 학습 여부 질문 ---
elif st.session_state.step == 'ASK_LEARN':
    st.title("💡 학습 제안")
    st.write("인식률을 높이기 위해 학습을 진행하시겠습니까?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("YES (학습하기)", use_container_width=True):
            st.session_state.step = 'CHOOSE_STORAGE'
            st.rerun()
    with col2:
        if st.button("NO (건너뛰기)", use_container_width=True):
            st.session_state.step = 'MAIN_NOTE'
            st.rerun()

# --- 3. 저장 방식 선택 ---
elif st.session_state.step == 'CHOOSE_STORAGE':
    st.title("🔒 데이터 저장 방식")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("내 기기에만 저장", use_container_width=True):
            st.session_state.storage = 'Local'
            st.session_state.step = 'NOTICE_TUTORIAL'
            st.rerun()
    with col2:
        if st.button("서버에 저장 (시뮬레이션)", use_container_width=True):
            st.session_state.storage = 'Cloud'
            st.session_state.step = 'NOTICE_TUTORIAL'
            st.rerun()

# --- 4. 튜토리얼 알림 ---
elif st.session_state.step == 'NOTICE_TUTORIAL':
    st.title("🚀 튜토리얼 모드")
    st.info(f"선택된 저장소: **{st.session_state.storage}**")
    if st.button("시작하기", type="primary", use_container_width=True):
        st.session_state.step = 'TUTORIAL_RUN'
        st.rerun()

# --- 5. 튜토리얼 진행 ---
elif st.session_state.step == 'TUTORIAL_RUN':
    idx = st.session_state.tutorial_idx
    target_text = pangrams[idx]
    
    st.subheader(f"📈 인식 정확도: {st.session_state.accuracy}%")
    st.progress(st.session_state.accuracy / 100)
    
    st.markdown(f"**단계 {idx + 1}. 아래 문장을 써주세요:**")
    st.markdown(f"## 👉 :blue[{target_text}]")
    
    grid_json = create_grid_drawing(target_text, width=1000, height=200)
    
    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#ffffff",
        initial_drawing=grid_json,
        update_streamlit=True,
        height=200,
        width=1000,
        drawing_mode="freedraw",
        key=f"canvas_{idx}"
    )
    
    if st.button("작성 완료 (Next)", type="primary"):
        if canvas_result.image_data is not None:
            # 이미지 저장 로직
            img_array = canvas_result.image_data.astype('uint8')
            image = Image.fromarray(img_array)
            img_bytes = BytesIO()
            image.save(img_bytes, format='PNG')
            final_data = img_bytes.getvalue()
            
            save_handwriting_image(final_data, target_text, st.session_state.storage)
            st.toast("💾 데이터 수집 및 저장 완료")

        with st.spinner("분석 중..."):
            time.sleep(0.5)
            st.session_state.accuracy = min(99, st.session_state.accuracy + 5)
            st.session_state.tutorial_idx += 1
            
        if st.session_state.tutorial_idx >= 3:
            st.session_state.step = 'TUTORIAL_CHOICE'
        st.rerun()

# --- 6. 완료 화면 ---
elif st.session_state.step == 'TUTORIAL_CHOICE':
    st.title("✅ 학습 완료")
    st.metric("최종 인식률", f"{st.session_state.accuracy}%")
    st.success(f"데이터가 '{st.session_state.storage}' 저장소에 안전하게 보관되었습니다.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("메인 노트로 이동"):
            st.session_state.step = 'MAIN_NOTE'
            st.rerun()
    with col2:
        if st.session_state.tutorial_idx < len(pangrams):
             if st.button("추가 학습하기"):
                st.session_state.step = 'TUTORIAL_RUN'
                st.rerun()

# --- 7. 메인 노트 ---
elif st.session_state.step == 'MAIN_NOTE':
    st.title("📝 나만의 AI 노트")
    st_canvas(stroke_width=2, stroke_color="#000", background_color="#fff", height=500, width=1000, key="main")
    if st.button("처음으로"):
        st.session_state.clear()
        st.rerun()