import sys
import os
import cv2
import winreg

from pynput import keyboard
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QIcon
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSystemTrayIcon, QMenu, QStyle

class EyeTrackerBackgroundApp(QWidget):
    # 📌 [스레드 안전 통신 시그널]
    # pynput 백그라운드 스레드에서 전역 단축키 감지 시, GUI 메인 스레드로 안전하게 신호를 보내기 위한 PyQt 시그널
    sig_toggle = pyqtSignal()
    
    # 📌 [단축키 설정 변수]
    # 언제든 원하는 조합으로 쉽게 변경할 수 있도록 상단에 분리한 전역 단축키 설정 값
    HOTKEY_COMBINATION = '<ctrl>+<alt>+c'
    HOTKEY_DISPLAY_NAME = 'Ctrl + Alt + C'

    def __init__(self):
        super().__init__()
        # 앱 창 기본 제목 및 크기 설정
        self.setWindowTitle("백그라운드 아이트래커 프로토타입")
        self.resize(640, 520)

        # 1. 윈도우 시작 프로그램 자동 등록 함수 호출 (부팅 시 자동 실행)
        self.register_startup()

        # UI 레이아웃 컨테이너 생성 및 위젯 배치 (웹캠 화면 + 상태 텍스트)
        layout = QVBoxLayout()

        # 웹캠 영상을 실시간으로 출력할 라벨 위젯
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        # 얼굴/눈 인식 상태 문구를 띄워줄 상태 표시 라벨 위젯
        self.status_label = QLabel("상태: 얼굴 및 눈 인식 대기 중...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

        # 2. 시스템 트레이 아이콘 및 우클릭 메뉴 설정 함수 호출
        self.setup_tray()

        # 3. OpenCV 웹캠 장치 초기화 (0번 기본 장치)
        self.cap = cv2.VideoCapture(0)
        
        # OpenCV 내장 얼굴 및 눈 검출용 Haar Cascade XML 모델 파일 경로 지정
        face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        eye_cascade_path = cv2.data.haarcascades + 'haarcascade_eye.xml'
        
        # 캐스케이드 분류기 객체 생성
        self.face_cascade = cv2.CascadeClassifier(face_cascade_path)
        self.eye_cascade = cv2.CascadeClassifier(eye_cascade_path)
        
        self.current_frame = None
        self.is_real_closing = False  # 트레이 메뉴의 '완전 종료'를 거쳤는지 판별하는 플래그 (일반 X 버튼은 트레이로 숨김)

        # 4. 화면 프레임 갱신 타이머 설정 (약 30fps 주기로 update_frame 함수 호출)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

        # 5. pynput을 이용한 전역(Global) 단축키 리스너 구동
        self.sig_toggle.connect(self.toggle_window)
        self.hotkey_listener = keyboard.GlobalHotKeys({
            self.HOTKEY_COMBINATION: self.sig_toggle.emit
        })
        self.hotkey_listener.start()

    def register_startup(self):
        """
        [시작 프로그램 등록 함수]
        Windows 레지스트리의 'Run' 키에 현재 스크립트 경로 또는 빌드된 .exe 경로를 등록하여,
        PC가 켜질 때 앱이 자동으로 백그라운드 구동되도록 만듭니다.
        """
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            # PyInstaller로 패키징된 .exe 상태인지, 파이썬 소스 코드(.py) 상태인지 확인하여 올바른 실행 경로 확보
            if getattr(sys, 'frozen', False):
                app_path = sys.executable
            else:
                app_path = os.path.abspath(__file__)
            
            # 레지스트리 키 오픈 후 값 쓰기
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "EyeTrackerBackgroundApp", 0, winreg.REG_SZ, f'"{app_path}"')
            winreg.CloseKey(key)
        except Exception as e:
            print(f"시작 프로그램 등록 실패: {e}")

    def setup_tray(self):
        """
        [시스템 트레이 설정 함수]
        작업표시줄 우측 하단 트레이 영역에 아이콘을 띄우고, 
        가비지 컬렉션(메모리 자동 해제)으로 인해 메뉴가 증발하지 않도록 self.tray_menu로 유지합니다.
        """
        self.tray_icon = QSystemTrayIcon(self)
        
        # # 트레이에 표시될 아이콘 지정 (아이콘 파일 로드)
        # self.tray_icon.setIcon(QIcon("icon.ico"))
        
        # # 우클릭 메뉴 컨테이너 생성 (self를 붙여 메모리 증발 방지)
        # self.tray_menu = QMenu()
        # 📌 외부 'icon.ico' 파일이 없어도 윈도우 기본 컴퓨터 아이콘을 강제로 띄워 눈에 보이게 함
        default_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon.setIcon(default_icon)
        
        # 메뉴 컨테이너 생성 (메모리 증발 방지)
        self.tray_menu = QMenu()

        # '화면 열기' 메뉴: 클릭 시 숨겨진 창을 다시 정위치로 복원
        show_action = self.tray_menu.addAction("화면 열기")
        show_action.triggered.connect(self.showNormal)
        
        # '완전 종료' 메뉴: 클릭 시 백그라운드 프로세스까지 메모리에서 완전히 해제
        exit_action = self.tray_menu.addAction("완전 종료")
        exit_action.triggered.connect(self.real_exit)
        
        # 트레이 아이콘에 컨텍스트 메뉴 장착 및 화면 표시
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        
        # 트레이 아이콘 더블클릭 시 창이 열리도록 이벤트 연결
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        """트레이 아이콘 마우스 인터랙션 처리 (더블클릭 시 창 복원)"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()

    def keyPressEvent(self, event):
        """
        [포커스 내 단축키 처리]
        앱 창이 활성화되어 포커스를 가졌을 때 Ctrl + Alt + C 입력을 감지하여 창 토글 수행
        """
        modifiers = event.modifiers()
        if (modifiers & Qt.KeyboardModifier.ControlModifier) and \
           (modifiers & Qt.KeyboardModifier.AltModifier) and \
           (event.key() == Qt.Key.Key_C):
            self.toggle_window()

    def toggle_window(self):
        """
        [창 상태 토글 함수]
        창이 숨겨져 있으면 화면 앞으로 띄우고 포커스를 주고, 
        화면에 보이고 있으면 트레이 백그라운드로 숨깁니다.
        """
        if self.isHidden():
            self.showNormal()
            self.raise_()
            self.activateWindow()
        else:
            self.hide()

    def update_frame(self):
        """
        [웹캠 프레임 갱신 및 AI 분석 루프]
        매 30프레임마다 웹캠으로부터 영상을 읽어와 좌우 반전 후,
        OpenCV 얼굴/눈 검출 모델을 돌려 사각형을 그리고 상태 텍스트와 UI 라벨을 갱신합니다.
        """
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.flip(frame, 1)  # 거울 모드 좌우 반전
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 얼굴 검출 수행
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100))
            
            face_detected = False
            for (x, y, w, h) in faces:
                face_detected = True
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)  # 얼굴 영역 초록 박스
                
                # 얼굴 내부에서 눈 영역 검출
                roi_gray = gray[y:y+h, x:x+w]
                roi_color = frame[y:y+h, x:x+w]
                eyes = self.eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=10, minSize=(20, 20))
                
                for (ex, ey, ew, eh) in eyes:
                    cv2.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), (255, 0, 0), 2)  # 눈 영역 파란 박스

            # 인식 여부에 따른 상태 UI 문구 및 색상 변경
            if face_detected:
                self.status_label.setText("상태: 얼굴 및 눈 인식 중 (정상 작동)")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.status_label.setText("상태: 사용자를 찾는 중...")
                self.status_label.setStyleSheet("color: gray;")

            self.current_frame = frame

            # OpenCV 이미지를 PyQt 포맷(QImage -> QPixmap)으로 변환하여 화면 라벨에 출력
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            q_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format.Format_RGB888)
            self.image_label.setPixmap(QPixmap.fromImage(q_image))

    def closeEvent(self, event):
        """
        [창 닫기(X 버튼) 가로채기 함수]
        사용자가 상단바의 X 버튼을 누를 때 진짜로 앱을 끄지 않고, 
        이벤트를 무시(ignore)한 뒤 창을 숨겨 백그라운드 트레이 모드로 전환합니다.
        """
        print("X 버튼 클릭됨! closeEvent 실행 중...")

        if not self.is_real_closing:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "백그라운드 실행 중",
                f"앱이 시스템 트레이로 숨었습니다. {self.HOTKEY_DISPLAY_NAME}를 누르거나 트레이 메뉴를 이용하세요.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            print("y 버튼 클릭됨! closeEvent 실행 중...")
        else:
            event.accept()

    def real_exit(self):
        """
        [진짜 완전 종료 함수]
        트레이 메뉴의 '완전 종료'를 눌렀을 때만 호출되며, 
        웹캠 장치를 반환하고 트레이 아이콘을 숨긴 뒤 어플리케이션 프로세스를 완전히 종료합니다.
        """
        self.is_real_closing = True
        self.cap.release()
        self.tray_icon.hide()
        QApplication.quit()

if __name__ == "__main__":
    # 프로그램 구동 진입점
    app = QApplication(sys.argv)
    # 마지막 남은 창이 닫혀도 프로세스가 자동 종료되지 않고 백그라운드에 상주하도록 설정
    app.setQuitOnLastWindowClosed(False)

    window = EyeTrackerBackgroundApp()
    window.show()
    sys.exit(app.exec())