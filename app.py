import streamlit as st
import time
from streamlit_drawable_canvas import st_canvas
import os
from datetime import datetime
from io import BytesIO, StringIO
from PIL import Image
import shutil
import pandas as pd # 엑셀(CSV) 처리를 위한 도구

# 구글 라이브러리들
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

# [중요] 버킷 이름 (기획자님의 실제 버킷 이름으로 유지하세요!)
BUCKET_NAME = "ainote-bucket-save1" 

# 폴더 생성
if not os.path.exists('user_data_local'): os.makedirs('user_data_local')
if not os.path.exists('dataset_verified'): os.makedirs('dataset_verified')
if not os.path.exists('dataset_trash'): os.makedirs('dataset_trash')

# ---------------------------------------------------------
# [NEW] 학습용 데이터셋(CSV) 저장 함수
# ---------------------------------------------------------
def log_result_to_csv(target_text, ocr_text, filename, bucket_name):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = storage.Client(credentials=creds, project=gcp_info["project_id"])
        bucket = client.bucket(bucket_name)
        blob = bucket.blob("training_data.csv") # 파일명 고정

        # 1. 새로운 데이터 한 줄 만들기
        new_row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_text": target_text,  # 정답 (콩)
            "ocr_text": ocr_text,        # AI 인식 (동)
            "is_correct": (target_text.replace(" ", "") == ocr_text.replace(" ", "")), # 정답 여부
            "filename": filename         # 이미지 파일명 (증거 자료)
        }
        new_df = pd.DataFrame([new_row])

        # 2. 기존 CSV가 있으면 다운로드해서 합치기
        if blob.exists():
            downloaded_blob = blob.download_as_text()
            existing_df = pd.read_csv(StringIO(downloaded_blob))
            updated_df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            updated_df = new_df

        # 3. 다시 클라우드에 업로드 (덮어쓰기)
        blob.upload_from_string(updated_df.to_csv(index=False), content_type='text/csv')
        return True
    except Exception as e:
        print(f"CSV Logging Error: {e}")
        return False

# ---------------------------------------------------------
# OCR 함수
# ---------------------------------------------------------
def detect_text_from_image(image_bytes):
    try:
        gcp_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(gcp_info)
        client = vision.ImageAnnotatorClient(credentials=creds)
        image = vision.Image(content=image_bytes)
        
        response = client.document_text_detection(image=image)
        text = response.full_text_annotation.text
        
        if response.error.message:
            return False, f"Error: {response.error.message}"
        return True, text
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------
# GCS 업로드 함수
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
# 저장 및 처리 메인 함수 (CSV 로깅 추가)
# ---------------------------------------------------------
def save_handwriting_image(image_data, text, storage_type):
    if image_data is None: return False, None, None, None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_text = text.replace(" ", "_") 
    filename = f"{timestamp}_{safe_text}.png"
    
    # 로컬 백업
    save_path = os.path.join('user_data_local', filename)
    with open(save_path, "wb") as f:
        f.write(image_data)
    
    upload_success = True
    ocr_result = "OCR 미실행"
    
    if storage_type == 'Cloud':
        with st.spinner("☁️ 클라우드 저장 및 학습 데이터 생성 중..."):
            # 1. 이미지 업로드
            success, msg = upload_to_gcs(image_data, filename, BUCKET_NAME)
            
            if success:
                # 2. OCR 실행
                ocr_success, detected_text = detect_text_from_image(image_data)
                
                if ocr_success:
                    ocr_result = detected_text
                    
                    # 3. [NEW] 결과(정답 vs 오답)를 CSV에 기록!
                    log_result_to_csv(text, ocr_result, filename, BUCKET_NAME)
                else:
                    ocr_result = "분석 실패"
            else:
                upload_success = False
                st.error(f"업로드 실패: {msg}")

    return upload_success, filename, save_path, ocr_result

# ---------------------------------------------------------
# 유틸리티 함수
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
# 관리자 대시보드 (CSV 다운로드 추가)
# ---------------------------------------------------------
def run_admin_dashboard():
    st.title("👨‍💻 데이터 품질 관리 센터 (QC)")
    st.caption("Server Status: Online 🟢")
    
    with st.sidebar:
        st.header("📦 데이터 반출")
        
        # [NEW] 학습 데이터(CSV) 다운로드 버튼
        st.subheader("📊 학습 데이터셋")
        try:
            gcp_info = st.secrets["gcp_service_account"]
            creds = service_account.Credentials.from_service_account_info(gcp_info)
            client = storage.Client(credentials=creds, project=gcp_info["project_id"])
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob("training_data.csv")
            
            if blob.exists():
                csv_data = blob.download_as_text()
                st.download_button(
                    label="📥 학습 데이터 다운로드 (.csv)",
                    data=csv_data,
                    file_name="handwriting_training_data.csv",
                    mime="text/csv",
                    type="primary"
                )
                st.success(f"현재 {len(csv_data.splitlines())-1}개의 데이터가 쌓였습니다.")
            else:
                st.info("아직 쌓인 데이터가 없습니다.")
        except Exception as e:
            st.error(f"데이터 로드 실패: {e}")

        st.markdown("---")
        # 서버 백업 다운로드
        if os.path.exists('user_data_local') and len(os.listdir('user_data_local')) > 0:
            shutil.make_archive('server_backup', 'zip', 'user_data_local')
            with open('server_backup.zip', 'rb') as f:
                st.download_button("📥 서버 원본 다운로드 (.zip)", f, "server_local_backup.zip", "application/zip")

    st.markdown("---")
    st.info("👈 사이드바에서 데이터를 다운로드하세요.")
    
    # (이미지 검수 기능은 생략 혹은 필요 시 유지)
    
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
            
            is_success, fname, fpath, ocr_result = save_handwriting_image(buf.getvalue(), target_text, st.session_state.storage)
            
            if is_success:
                if st.session_state.storage == 'Cloud':
                    st.success("☁️ 저장 및 데이터 로깅 완료!")
                    st.markdown("---")
                    st.subheader("🤖 AI 인식 결과")
                    st.write(f"**AI 인식:** {ocr_result}")
                    st.caption(f"**목표 정답:** {target_text}")
                    
                    # 간단 비교 및 피드백
                    clean_target = target_text.replace(" ", "")
                    clean_ocr = ocr_result.replace(" ", "")
                    
                    if clean_target == clean_ocr:
                        st.balloons()
                        st.info("🎉 완벽합니다! AI가 정답을 맞췄습니다.")
                    else:
                        st.warning("🧐 AI가 헷갈려하네요. 이 데이터는 '오답 노트'에 기록되어 AI를 가르치는 데 사용됩니다!")
                        
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