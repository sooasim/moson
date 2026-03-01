# 전체 오류 검사 및 100회 시뮬레이션 결과

## 실행 방법
```bash
python run_health_check.py
```

## 검사 항목 (8단계)

| 단계 | 내용 | 반복 |
|------|------|------|
| 1 | **문법 검사** – 프로젝트 내 모든 `.py` 파일 `py_compile` | 1회 |
| 2 | **앱 import** – `create_app()` 및 모듈 로드 | 1회 |
| 3 | **라우트 GET** – 주요 8개 URL GET 요청 (500/예외 여부) | **100회** |
| 4 | **정책 업로드 POST** – `/admin/policy/import-upload` POST (파일 없이) | **50회** |
| 5 | **템플릿 렌더** – 랜딩 페이지 GET 후 본문 키워드 확인 | 1회 |
| 6 | **policy_import** – 존재하지 않는 파일로 호출 시 `(False, str, 0)` 반환 | 1회 |
| 7 | **policy_export** – `build_policy_xlsx([])` 호출 시 bytes 반환 | 1회 |
| 8 | **/consult POST** – 빈 폼 제출 (500 여부) | **30회** |

## 검사 대상 라우트 (100회 x 8)
- `/` (랜딩)
- `/admin/`
- `/admin/login`
- `/admin/policy`
- `/admin/policy/import-upload` (GET → 302)
- `/partner/apply`
- `/api/policy-quote`
- `/favicon.ico`

## 결과
- **문법/들여쓰기**: 오류 없음
- **import**: 정상
- **라우트 800회(100x8)**: 500/예외 없음
- **POST 50회 + 30회**: 500/예외 없음
- **policy_import/export**: 반환값 정상

## 사용자 입장 점검
- 랜딩 페이지 정상 렌더, 본문에 사이트 키워드 포함
- 정책 업로드 실패 시 500 대신 redirect + flash
- 정책표 페이지 Cache-Control no-store 적용
- 정책표 아이콘 인라인 SVG로 CDN 없이 표시
