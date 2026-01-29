import streamlit as st
import time
from streamlit_drawable_canvas import st_canvas
import os
from datetime import datetime
from io import BytesIO, StringIO
from PIL import Image
import shutil
import pandas as pd

from google.cloud import storage
from google.cloud import vision
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

# [중요] 버킷 이름 유지
BUCKET_NAME = "ainote-bucket-save1" 

if not os.path.exists('user_data_local'): os.makedirs('user_data_local')
if not os.path.exists('dataset_verified'): os.makedirs('dataset_verified')
if not os.path.exists('dataset_trash'): os.makedirs('dataset_trash')

# ---------------------------------------------------------
# [NEW] CSV 로깅 함수 (User ID 추가됨)
# ---------------------------------------------------------
def log_result_to_csv(user_id, target_text, ocr_text, filename, bucket_name):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = storage.Client(credentials=creds, project=gcp_info["project_id"])
        bucket = client.bucket(bucket_name)
        blob = bucket.blob("training_data.csv")

        new_row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id,          # [NEW] 사용자 구분 키!
            "target_text": target_text,
            "ocr_text": ocr_text,
            "is_correct": (target_text.replace(" ", "") == ocr_text.replace(" ", "")),
            "filename": filename
        }
        new_df = pd.DataFrame([new_row])

        if blob.exists():
            downloaded_blob = blob.download_as_text()
            existing_df = pd.read_csv(StringIO(downloaded_blob))
            updated_df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            updated_df = new_df

        blob.upload_from_string(updated_df.to_csv(index=False), content_type='text/csv')
        return True
    except Exception as e:
        print(f"CSV Logging Error: {e}")
        return False

# ---------------------------------------------------------
# OCR & Upload 함수 (기존 동일)
# ---------------------------------------------------------
def detect_text_from_image(image_bytes):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = vision.ImageAnnotatorClient(credentials=creds)
        image = vision.Image(content=image_bytes)
        response = client.document_text_detection(image=image)
        text = response.full_text_annotation.text
        if response.error.message: return False, f"Error: {response.error.message}"
        return True, text
    except Exception as e: return False, str(e)

def upload_to_gcs(file_bytes, filename, bucket_name):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = storage.Client(credentials=creds, project=gcp_info["project_id"])
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(file_bytes, content_type='image/png')
        return True, filename
    except Exception as e: return False, str(e)

# ---------------------------------------------------------
# [수정] 메인 저장 함수 (user_id를 받도록 변경)
# ---------------------------------------------------------
def save_handwriting_image(image_data, text, storage_type, user_id):
    if image_data is None: return False, None, None, None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 파일명에도 ID를 넣으면 나중에 찾기 쉽습니다! (예: userA_20260129_...)
    safe_text = text.replace(" ", "_") 
    filename = f"{user_id}_{timestamp}_{safe_text}.png"
    
    save_path = os.path.join('user_data_local', filename)
    with open(save_path, "wb") as f:
        f.write(image_data)
    
    upload_success = True
    ocr_result = "OCR 미실행"
    
    if storage_type == 'Cloud':
        with st.spinner("☁️ 저장 및 분석 중..."):
            success, msg = upload_to_gcs(image_data, filename, BUCKET_NAME)
            if success:
                ocr_success, detected_text = detect_text_from_image(image_data)
                if ocr_success:
                    ocr_result = detected_text
                    # [NEW] ID도 함께 기록
                    log_result_to_csv(user_id, text, ocr_result, filename, BUCKET_NAME)
                else:
                    ocr_result = "분석 실패"
            else:
                upload_success = False
                st.error(f"업로드 실패: {msg}")

    return upload_success, filename, save_path, ocr_result

# ---------------------------------------------------------
# 유틸리티 & 관리자 (기존 동일)
# ---------------------------------------------------------
def create_grid_drawing(text, width=1000, height=200):
    if len(text) == 0: return None
    step_x = width / len(text)
    objects = []
    for i in range(1, len(text)):
        x = i * step_x
        line = {"type": "line", "x1": x, "y1": 20, "x2": x, "y2": height - 20, "stroke": "#cccccc", "strokeWidth": 2, "selectable": False}
        objects.append(line)
    return {"version": "4.4.0", "objects": objects}

def run_admin_dashboard():
    st.title("👨‍💻 데이터 품질 관리 센터 (QC)")
    with st.sidebar:
        st.header("📦 데이터 반출")
        st.subheader("📊 학습 데이터셋")
        try:
            gcp_info = st.secrets["gcp_service_account"]
            creds = service_account.Credentials.from_service_account_info(gcp_info)
            client = storage.Client(credentials=creds, project=gcp_info["project_id"])
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("training_data.csv")
            if blob.exists():
                csv_data = blob.download_as_text()
                st.download_button("📥 학습 데이터 다운로드 (.csv)", csv_data, "training_data.csv", "text/csv", type="primary")
                st.success(f"{len(csv_data.splitlines())-1}건의 데이터 보유 중")
            else: st.info("데이터 없음")
        except Exception as e: st.error(f"Error: {e}")
        
        st.markdown("---")
        if os.path.exists('user_data_local'):
            shutil.make_archive('server_backup', 'zip', 'user_data_local')
            with open('server_backup.zip', 'rb') as f:
                st.download_button("📥 서버 원본 다운로드 (.zip)", f, "server_backup.zip")

# ---------------------------------------------------------
# 실행 로직
# ---------------------------------------------------------
if 'step' not in st.session_state: st.session_state.step = 'WELCOME'
if 'accuracy' not in st.session_state: st.session_state.accuracy = 70
if 'tutorial_idx' not in st.session_state: st.session_state.tutorial_idx = 0
if 'storage' not in st.session_state: st.session_state.storage = 'Local'
# [NEW] 사용자 ID 상태 추가
if 'user_id' not in st.session_state: st.session_state.user_id = "Guest"

pangrams = ["다람쥐 헌 쳇바퀴에 타고파", "닭 콩팥 훔친 집사", "물컵 속 팥 찾던 형"]

with st.sidebar:
    st.markdown("<h1 style='color: #FF4B4B; margin:0;'>AI NOTE</h1>", unsafe_allow_html=True)
    st.caption("Target: Global No.1")
    
    # [NEW] 사용자 구분용 입력창
    st.markdown("---")
    st.session_state.user_id = st.text_input("👤 사용자 ID (닉네임)", value=st.session_state.user_id)
    st.info(f"현재 사용자: **{st.session_state.user_id}**")
    st.markdown("---")

    is_admin = st.checkbox("관리자 모드 (Admin)", value=False)

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
    st.info(f"사용자: **{st.session_state.user_id}** | 저장소: **{st.session_state.storage}**")
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
            
            # [수정] user_id를 함께 전달!
            is_success, fname, fpath, ocr_result = save_handwriting_image(
                buf.getvalue(), 
                target_text, 
                st.session_state.storage, 
                st.session_state.user_id # <--- [Important]
            )
            
            if is_success:
                if st.session_state.storage == 'Cloud':
                    st.success(f"☁️ [{st.session_state.user_id}]님의 데이터 저장 완료!")
                    st.markdown("---")
                    st.subheader("🤖 AI 인식 결과")
                    st.write(f"**AI 인식:** {ocr_result}")
                    
                    clean_target = target_text.replace(" ", "")
                    clean_ocr = ocr_result.replace(" ", "")
                    
                    if clean_target == clean_ocr:
                        st.balloons()
                        st.info("🎉 정답입니다!")
                    else:
                        st.warning("🧐 오답 노트에 기록되었습니다.")
                    st.markdown("---")
                    time.sleep(3)
                else:
                    st.success("💾 로컬 저장 완료")
                    time.sleep(1)

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