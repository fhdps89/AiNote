import streamlit as st
import time
from streamlit_drawable_canvas import st_canvas
import os
from datetime import datetime
from io import BytesIO
from PIL import Image
import shutil

# 구글 라이브러리들
from google.cloud import storage
from google.cloud import vision  # [NEW] Vision API 추가
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

# [설정] 버킷 이름 (기존 그대로 유지)
BUCKET_NAME = "ainote-bucket-yua" 

# 폴더 생성
if not os.path.exists('user_data_local'): os.makedirs('user_data_local')
if not os.path.exists('dataset_verified'): os.makedirs('dataset_verified')
if not os.path.exists('dataset_trash'): os.makedirs('dataset_trash')

# ---------------------------------------------------------
# [NEW] OCR 함수 (AI가 글씨 읽기)
# ---------------------------------------------------------
def detect_text_from_image(image_bytes):
    try:
        # 1. 인증 정보 가져오기
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        
        # 2. Vision API 클라이언트 연결
        client = vision.ImageAnnotatorClient(credentials=creds)
        image = vision.Image(content=image_bytes)

        # 3. 텍스트 감지 요청 (Handwriting에 강한 document_text_detection 사용)
        response = client.document_text_detection(image=image)
        text = response.full_text_annotation.text
        
        if response.error.message:
            return False, f"Error: {response.error.message}"
            
        return True, text
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------
# GCS 업로드 함수 (기존 유지)
# ---------------------------------------------------------
def upload_to_gcs(file_bytes, filename, bucket_name):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = storage.Client(credentials=creds, project=gcp_info["project_id"])
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(file_bytes, content_type='image/png')
        return True, filename
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------
# 저장 및 처리 함수 (OCR 기능 통합)
# ---------------------------------------------------------
def save_handwriting_image(image_data, text, storage_type):
    if image_data is None: return False, None, None, None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_text = text.replace(" ", "_") 
    filename = f"{timestamp}_{safe_text}.png"
    
    # 1. 로컬 저장
    save_path = os.path.join('user_data_local', filename)
    with open(save_path, "wb") as f:
        f.write(image_data)
    
    upload_success = True
    ocr_result = "OCR 미실행" # 초기값
    
    # 2. 클라우드 업로드
    if storage_type == 'Cloud':
        with st.spinner("☁️ 클라우드 저장 및 AI 분석 중..."):
            # A. 업로드
            success, msg = upload_to_gcs(image_data, filename, BUCKET_NAME)
            
            # B. [NEW] OCR 분석 실행!
            if success:
                st.toast("업로드 완료! 이제 글씨를 읽습니다...")
                ocr_success, detected_text = detect_text_from_image(image_data)
                
                if ocr_success:
                    ocr_result = detected_text
                else:
                    ocr_result = "분석 실패"
            else:
                upload_success = False
                st.error(f"업로드 실패: {msg}")

    return upload_success, filename, save_path, ocr_result

# ---------------------------------------------------------
# 유틸리티 함수 (그리드 등)
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

# ---------------------------------------------------------
# 관리자 대시보드
# ---------------------------------------------------------
def run_admin_dashboard():
    st.title("👨‍💻 데이터 품질 관리 센터 (QC)")
    st.caption("Server Status: Online 🟢")
    
    with st.sidebar:
        st.header("📦 데이터 반출")
        # 서버 백업 다운로드
        if os.path.exists('user_data_local') and len(os.listdir('user_data_local')) > 0:
            shutil.make_archive('server_backup', 'zip', 'user_data_local')
            with open('server_backup.zip', 'rb') as f:
                st.download_button("📥 서버 원본 다운로드", f, "server_local_backup.zip", "application/zip", type="primary")
                
    st.markdown("---")
    
    pending_files = [f for f in os.listdir('user_data_local') if f.endswith('.png')]
    verified_files = [f for f in os.listdir('dataset_verified') if f.endswith('.png')]
    
    col1, col2 = st.columns(2)
    col1.metric("대기 중", f"{len(pending_files)}건")
    col2.metric("승인됨", f"{len(verified_files)}건")

    if len(pending_files) == 0:
        st.info("대기 중인 데이터가 없습니다.")
        return

    for idx, filename in enumerate(pending_files):
        file_path = os.path.join('user_data_local', filename)
        if idx % 3 == 0: cols = st.columns(3)
        with cols[idx % 3]:
            try:
                img = Image.open(file_path)
                st.image(img, use_container_width=True)
                if st.button("✅ 승인", key=f"ok_{filename}"):
                    shutil.move(file_path, os.path.join('dataset_verified', filename))
                    st.rerun()
                if st.button("🗑 삭제", key=f"del_{filename}"):
                    shutil.move(file_path, os.path.join('dataset_trash', filename))
                    st.rerun()
            except: pass

# ---------------------------------------------------------
# 메인 실행 로직
# ---------------------------------------------------------
if 'step' not in st.session_state: st.session_state.step = 'WELCOME'
if 'accuracy' not in st.session_state: st.session_state.accuracy = 70
if 'tutorial_idx' not in st.session_state: st.session_state.tutorial_idx = 0
if 'storage' not in st.session_state: st.session_state.storage = 'Local'

pangrams = ["다람쥐 헌 쳇바퀴에 타고파", "닭 콩팥 훔친 집사", "물컵 속 팥 찾던 형"]

with st.sidebar:
    st.markdown("<h1 style='color: #FF4B4B; margin:0;'>AI NOTE</h1>", unsafe_allow_html=True)
    st.caption("Target: Global No.1")
    is_admin = st.checkbox("관리자 모드 (Admin)", value=False)

# 비밀번호 보호된 관리자 모드
if is_admin:
    password = st.sidebar.text_input("🔑 관리자 암호 입력", type="password")
    if password == st.secrets["admin_password"]:
        st.sidebar.success("접속 승인! 🔓")
        run_admin_dashboard()
        st.stop()
    elif password:
        st.sidebar.error("암호 오류")
        st.stop()
    else:
        st.sidebar.warning("암호를 입력하세요.")
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
    
    if st.button("저장 & AI 분석 (Save)", type="primary"):
        if canvas.image_data is not None:
            img = Image.fromarray(canvas.image_data.astype('uint8'))
            buf = BytesIO()
            img.save(buf, format='PNG')
            
            # [NEW] ocr_result까지 받아옵니다!
            is_success, fname, fpath, ocr_result = save_handwriting_image(buf.getvalue(), target_text, st.session_state.storage)
            
            if is_success:
                # -------------------------------------------
                # 🎉 AI 결과 발표 (여기가 하이라이트!)
                # -------------------------------------------
                if st.session_state.storage == 'Cloud':
                    st.success("☁️ 저장 완료!")
                    st.markdown("---")
                    st.subheader("🤖 AI 인식 결과")
                    
                    # 정답과 비교
                    st.write(f"**내가 쓴 글씨:** {ocr_result}")
                    st.caption(f"**목표 문장:** {target_text}")
                    
                    # 정확도 평가 (간단 비교)
                    if target_text.replace(" ","") in ocr_result.replace(" ","") or ocr_result.strip() in target_text:
                        st.balloons() # 정답이면 풍선 날리기!
                        st.info("🎉 정확합니다! AI가 완벽하게 읽었네요.")
                    else:
                        st.warning("🤔 음.. 조금 다르게 읽었네요. 글씨를 더 또박또박 써보세요!")
                    
                    st.markdown("---")
                    time.sleep(3) # 결과를 볼 시간 3초 줌
                else:
                    st.success("💾 로컬 저장 완료 (OCR은 클라우드 모드에서만 동작합니다)")
                    time.sleep(1)

                # 다음 단계로
                st.session_state.accuracy += 5
                st.session_state.tutorial_idx += 1
                if st.session_state.tutorial_idx >= len(pangrams):
                    st.session_state.step = 'TUTORIAL_CHOICE'
                st.rerun()
            else:
                st.warning("⚠️ 저장 실패")

elif st.session_state.step == 'TUTORIAL_CHOICE':
    st.title("✅ 완료!")
    st.success("모든 데이터가 저장되었습니다.")
    if st.button("메인 노트로 이동"):
        st.session_state.step = 'MAIN_NOTE'
        st.rerun()

elif st.session_state.step == 'MAIN_NOTE':
    st.title("📝 메인 노트")
    st_canvas(height=500, width=1000, key="main")