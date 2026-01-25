import streamlit as st
import time
from streamlit_drawable_canvas import st_canvas
import os
from datetime import datetime
from io import BytesIO
from PIL import Image
import shutil

# --- [NEW] 구글 클라우드 스토리지 라이브러리 ---
from google.cloud import storage
from google.oauth2 import service_account

# ---------------------------------------------------------
# [설정] 앱 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Note Pro",
    page_icon="📝",
    layout="centered",
    initial_sidebar_state="expanded"
)

# [중요] 여기에 아까 만든 버킷 이름을 넣으세요! (따옴표 필수)
BUCKET_NAME = "ainote-bucket-save1"  # <--- 본인이 만든 버킷 이름으로 변경!

# 폴더 생성
if not os.path.exists('user_data_local'): os.makedirs('user_data_local')
if not os.path.exists('dataset_verified'): os.makedirs('dataset_verified')
if not os.path.exists('dataset_trash'): os.makedirs('dataset_trash')

# ---------------------------------------------------------
# [NEW] GCS 업로드 함수 (여기가 바뀜)
# ---------------------------------------------------------
def upload_to_gcs(file_bytes, filename, bucket_name):
    try:
        # 1. Secrets에서 로봇 신분증 꺼내기
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        
        # 2. 클라이언트 연결 & 버킷 선택
        client = storage.Client(credentials=creds, project=gcp_info["project_id"])
        bucket = client.bucket(bucket_name)
        
        # 3. 파일 업로드 (Blob 만들기)
        blob = bucket.blob(filename)
        blob.upload_from_string(file_bytes, content_type='image/png')
        
        return True, filename
        
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------
# 기존 함수들 (그대로 유지)
# ---------------------------------------------------------
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

def save_handwriting_image(image_data, text, storage_type):
    if image_data is None: return False, None, None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_text = text.replace(" ", "_") 
    filename = f"{timestamp}_{safe_text}.png"
    
    # 1. 로컬 저장
    save_path = os.path.join('user_data_local', filename)
    with open(save_path, "wb") as f:
        f.write(image_data)
    
    upload_success = True
    
    # 2. 클라우드(GCS) 업로드 시도
    if storage_type == 'Cloud':
        with st.spinner(f"☁️ 클라우드(GCS)로 전송 중..."):
            success, msg = upload_to_gcs(image_data, filename, BUCKET_NAME)
            
        if success:
            st.toast(f"✅ 업로드 성공! (GCS: {msg})")
            st.success(f"클라우드 저장 완료: {filename}")
        else:
            st.error(f"❌ 업로드 실패! 이유를 확인하세요:\n{msg}")
            upload_success = False 
            
    return upload_success, filename, save_path

# --- [NEW] 서버 내부 데이터 다운로드 기능이 추가된 관리자 모드 ---
def run_admin_dashboard():
    st.title("👨‍💻 데이터 품질 관리 센터 (QC)")
    st.caption("Server Status: Online 🟢")
    
    # 1. 사이드바: 데이터 반출 (기존 기능 + NEW 로컬 백업 다운로드)
    with st.sidebar:
        st.header("📦 데이터 반출")
        
        # [기존] 승인된 데이터셋 다운로드
        if os.path.exists('dataset_verified') and len(os.listdir('dataset_verified')) > 0:
            shutil.make_archive('verified_dataset', 'zip', 'dataset_verified')
            with open('verified_dataset.zip', 'rb') as f:
                st.download_button("📥 승인 데이터셋 (.zip)", f, "verified_dataset.zip", "application/zip", type="primary")
        
        st.markdown("---")
        
        # [NEW] 서버에 고립된 '로컬 백업' 파일 구조대
        st.subheader("🆘 서버 원본 파일 구조")
        st.info("미국 서버의 'user_data_local' 폴더를 강제로 가져옵니다.")
        
        if os.path.exists('user_data_local') and len(os.listdir('user_data_local')) > 0:
            # 폴더 통째로 압축
            shutil.make_archive('server_backup', 'zip', 'user_data_local')
            
            with open('server_backup.zip', 'rb') as f:
                st.download_button(
                    label="📥 서버 원본 다운로드 (Backup)",
                    data=f,
                    file_name="server_local_backup.zip",
                    mime="application/zip",
                    use_container_width=True
                )
        else:
            st.warning("서버에 저장된 로컬 파일이 없습니다.")

    st.markdown("---")
    
    # ... (아래는 기존의 현황판 및 검수 UI 코드 그대로 유지) ...
    # 파일 현황 파악
    pending_files = [f for f in os.listdir('user_data_local') if f.endswith('.png')]
    verified_files = [f for f in os.listdir('dataset_verified') if f.endswith('.png')]
    trash_files = [f for f in os.listdir('dataset_trash') if f.endswith('.png')]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("서버 로컬 저장소", f"{len(pending_files)}건", delta="확인 불가" if len(pending_files)==0 else "다운 가능")
    col2.metric("승인됨", f"{len(verified_files)}건")
    col3.metric("휴지통", f"{len(trash_files)}건")

    if len(pending_files) == 0:
        st.success("🎉 현재 대기 중인 데이터가 없습니다.")
        return

    # 검수 인터페이스 (기존 코드)
    for idx, filename in enumerate(pending_files):
        file_path = os.path.join('user_data_local', filename)
        if idx % 3 == 0: cols = st.columns(3)
        with cols[idx % 3]:
            try:
                img = Image.open(file_path)
                st.image(img, use_container_width=True)
                b_col1, b_col2 = st.columns(2)
                if b_col1.button("✅", key=f"ok_{filename}"):
                    shutil.move(file_path, os.path.join('dataset_verified', filename))
                    st.rerun()
                if b_col2.button("🗑", key=f"del_{filename}"):
                    shutil.move(file_path, os.path.join('dataset_trash', filename))
                    st.rerun()
            except: pass

# ---------------------------------------------------------
# 앱 실행 로직
# ---------------------------------------------------------
if 'step' not in st.session_state: st.session_state.step = 'WELCOME'
if 'accuracy' not in st.session_state: st.session_state.accuracy = 70
if 'tutorial_idx' not in st.session_state: st.session_state.tutorial_idx = 0
if 'storage' not in st.session_state: st.session_state.storage = 'Local'

pangrams = ["다람쥐 헌 쳇바퀴에 타고파", "닭 콩팥 훔친 집사", "물컵 속 팥 찾던 형"]

with st.sidebar:
    st.markdown("<h1 style='color: #FF4B4B; margin:0;'>AI NOTE</h1>", unsafe_allow_html=True)
    st.caption("Target: Global No.1")
    st.markdown("---")
    is_admin = st.checkbox("관리자 모드 (Admin)", value=False)

if is_admin:
    run_admin_dashboard()
    st.stop()

if st.session_state.step == 'WELCOME':
    st.markdown("<br><br><h1 style='text-align: center;'>✍️ 환영합니다</h1>", unsafe_allow_html=True)
    time.sleep(2)
    st.session_state.step = 'ASK_LEARN'
    st.rerun()

elif st.session_state.step == 'ASK_LEARN':
    st.title("💡 학습 제안")
    if st.button("YES (학습하기)", use_container_width=True):
        st.session_state.step = 'CHOOSE_STORAGE'
        st.rerun()
    if st.button("NO (건너뛰기)", use_container_width=True):
        st.session_state.step = 'MAIN_NOTE'
        st.rerun()

elif st.session_state.step == 'CHOOSE_STORAGE':
    st.title("🔒 저장 위치 선택")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("내 기기에만 저장", use_container_width=True):
            st.session_state.storage = 'Local'
            st.session_state.step = 'NOTICE_TUTORIAL'
            st.rerun()
    with col2:
        # 이름 변경: 구글 드라이브 -> 클라우드 스토리지
        if st.button("☁️ 클라우드(GCS) 연동", use_container_width=True):
            st.session_state.storage = 'Cloud'
            st.session_state.step = 'NOTICE_TUTORIAL'
            st.rerun()

elif st.session_state.step == 'NOTICE_TUTORIAL':
    st.title("🚀 튜토리얼 모드")
    st.info(f"선택된 저장소: **{st.session_state.storage}**")
    if st.button("시작하기", type="primary"):
        st.session_state.step = 'TUTORIAL_RUN'
        st.rerun()

elif st.session_state.step == 'TUTORIAL_RUN':
    idx = st.session_state.tutorial_idx
    target_text = pangrams[idx]
    
    st.progress(st.session_state.accuracy / 100)
    st.markdown(f"## 👉 :blue[{target_text}]")
    
    grid_json = create_grid_drawing(target_text)
    canvas = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=3, # 펜 두께 정상
        stroke_color="#000000",
        background_color="#ffffff",
        initial_drawing=grid_json,
        update_streamlit=True,
        height=200,
        width=1000,
        drawing_mode="freedraw",
        key=f"canvas_{idx}"
    )
    
    if st.button("저장 (Save)", type="primary"):
        if canvas.image_data is not None:
            img = Image.fromarray(canvas.image_data.astype('uint8'))
            buf = BytesIO()
            img.save(buf, format='PNG')
            
            # 저장 함수 호출 (성공/실패 감지)
            is_success, fname, fpath = save_handwriting_image(buf.getvalue(), target_text, st.session_state.storage)
            
            if is_success:
                st.session_state.accuracy += 5
                st.session_state.tutorial_idx += 1
                if st.session_state.tutorial_idx >= len(pangrams):
                    st.session_state.step = 'TUTORIAL_CHOICE'
                st.rerun()
            else:
                st.warning("⚠️ 클라우드 업로드에 실패했습니다. 에러 메시지를 확인하세요.")

elif st.session_state.step == 'TUTORIAL_CHOICE':
    st.title("✅ 완료!")
    st.success("모든 데이터가 안전하게 저장되었습니다.")
    if st.button("메인 노트로 이동"):
        st.session_state.step = 'MAIN_NOTE'
        st.rerun()

elif st.session_state.step == 'MAIN_NOTE':
    st.title("📝 메인 노트")
    st_canvas(height=500, width=1000, key="main")