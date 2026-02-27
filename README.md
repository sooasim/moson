# MOSON.life Flask MVP (멀티 대리점/서브도메인)

## 1) 실행 (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

- 메인 사이트: http://127.0.0.1:5000
- 메인 어드민: http://127.0.0.1:5000/admin (기본: admin / admin1234)

## 2) 대리점(리셀러) 생성

1. 메인 어드민 로그인
2. **대리점 관리 → 대리점 생성**
3. 생성 후 아래가 자동 동작
   - 대리점 레코드 저장
   - 동일 랜딩페이지가 **서브도메인 테넌트**로 동작 (업체명/전화/이메일 자동 반영)
   - 신청서(견적/가입)가 들어오면 **대리점 이메일 + moson 이메일로 동시 발송**
   - 메인 어드민에서는 모든 대리점/모든 신청을 통합 조회

### 로컬에서 서브도메인 테스트 (둘 중 하나)

- 방법 A) URL 파라미터로 강제 테넌트
  - 예: `http://127.0.0.1:5000/?dealer=daelim01`

- 방법 B) hosts 파일에 매핑 (권장)
  - Windows: `C:\Windows\System32\drivers\etc\hosts`
  - 아래처럼 추가
    ```
    127.0.0.1  daelim01.moson.life
    ```
  - 접속: `http://daelim01.moson.life:5000`

## 3) 대리점 어드민

- URL: `http://<subdomain>.moson.life/admin`
- 로그인: **대리점 이메일 / 초기 비밀번호**
- 본인 사이트에서 받은 신청만 조회됩니다.

## 4) Cloudflare SSL / 서브도메인 운영 권장 설정

가장 쉬운 방식은 **와일드카드 DNS** 입니다.

1. Cloudflare DNS에서 `A` 레코드 생성
   - Name: `*`
   - Target: 서버 공인 IP
   - Proxy: ON (주황 구름)
2. SSL/TLS 모드: `Full (strict)` 권장
3. 서버는 80/443을 열고, 실제 배포는 gunicorn/uwsgi + nginx 등 WSGI로 운영

> 이 MVP는 Flask 개발서버로 동작하지만, 실제 운영에는 WSGI 서버를 쓰세요.

## 5) SMTP 설정

`.env`에 SMTP 값을 넣으면 실제 이메일 발송,
안 넣으면 콘솔에 [EMAIL:DRYRUN] 형태로 출력합니다.

## 6) DB

- 기본 SQLite: `instance/moson.sqlite3`
