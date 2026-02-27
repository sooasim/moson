from app import create_app

# Plesk / IIS / WSGI 서버에서 사용할 엔트리 포인트
# 예: WSGI_HANDLER=wsgi.app
app = create_app()

