from app import create_app

# Plesk / Passenger용 WSGI 엔트리 포인트
# Plesk의 Python 애플리케이션 설정에서 이 파일을 엔트리로 사용합니다.
#
# 예: Document root 를 이 프로젝트 루트로 설정하고,
#     "Application startup file" 에 passenger_wsgi.py 를 지정합니다.

application = create_app()

