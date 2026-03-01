# -*- coding: utf-8 -*-
"""전체 오류 검사 및 100회 시뮬레이션."""
import sys
import traceback

def phase1_syntax():
    """1. 모든 .py 파일 문법 검사."""
    import py_compile
    import os
    errors = []
    for root, _, files in os.walk("."):
        if "__pycache__" in root or ".git" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    py_compile.compile(path, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append((path, str(e)))
    return errors

def phase2_import():
    """2. 앱 및 모듈 import."""
    try:
        from app import create_app
        app = create_app()
        return None, app
    except Exception as e:
        return (traceback.format_exc(), None)

def phase3_routes(app, n=100):
    """3. 주요 라우트 N회 요청 (GET) - 500/예외 없어야 함."""
    client = app.test_client()
    routes = [
        ("/", "랜딩"),
        ("/admin/", "어드민"),
        ("/admin/login", "어드민 로그인"),
        ("/admin/policy", "정책표"),
        ("/admin/policy/import-upload", "정책 업로드 GET"),
        ("/partner/apply", "부업 파트너 신청"),
        ("/api/policy-quote", "API 정책 견적"),
        ("/favicon.ico", "파비콘"),
    ]
    errors = []
    for i in range(n):
        for path, label in routes:
            try:
                r = client.get(path, follow_redirects=False)
                if r.status_code >= 500:
                    errors.append((path, label, r.status_code, "서버 에러"))
            except Exception as e:
                errors.append((path, label, None, str(e)))
    return errors

def phase4_post_safety(app, n=50):
    """4. POST 엔드포인트 안전 호출 (파일 없이 등) - 400/302는 허용, 500/예외는 수집."""
    client = app.test_client()
    errors = []
    # 정책 업로드 POST: 파일 없이 -> 302 + flash 기대
    for i in range(n):
        try:
            r = client.post("/admin/policy/import-upload", data={}, follow_redirects=False)
            if r.status_code >= 500:
                errors.append(("/admin/policy/import-upload POST", r.status_code, "서버 에러"))
        except Exception as e:
            errors.append(("/admin/policy/import-upload POST", None, str(e)))
    return errors

def phase5_templates(app):
    """5. 주요 템플릿 렌더 (요청 컨텍스트 내)."""
    client = app.test_client()
    # 로그인 페이지는 302일 수 있음. GET / 은 200 또는 302
    try:
        r = client.get("/", follow_redirects=True)
        if r.status_code != 200:
            return [("GET / (follow)", r.status_code)]
        html = r.data.decode("utf-8", errors="replace")
        if "모손" not in html and "MOSON" not in html and "moson" not in html:
            return [("GET /", "랜딩 본문 키워드 없음")]
    except Exception as e:
        return [("GET /", str(e))]
    return []

def phase6_policy_import_module():
    """6. policy_import 함수 시그니처 및 예외 처리."""
    from app.policy_import import run_policy_import
    from app import create_app
    app = create_app()
    with app.app_context():
        ok, msg, cnt = run_policy_import(app, xlsx_path="/nonexistent/file.xlsx")
        if ok is not False:
            return [("policy_import 반환", "실패 시 success=False 기대")]
        if not isinstance(msg, str):
            return [("policy_import 메시지", "str 기대")]
    return []

def phase7_policy_export(app):
    """7. policy_export 모듈 (export 시 로그인 필요해 302 가능)."""
    try:
        from app.policy_export import build_policy_xlsx
        from app.models import PolicyRow
        xlsx_bytes = build_policy_xlsx([])
        if not isinstance(xlsx_bytes, bytes):
            return [("build_policy_xlsx", "bytes 반환 기대")]
    except Exception as e:
        return [("policy_export", str(e))]
    return []

def phase8_consult_post(app, n=30):
    """8. /consult POST (필수 필드 없이) - 400/302 허용, 500 수집."""
    client = app.test_client()
    errors = []
    for _ in range(n):
        try:
            r = client.post("/consult", data={}, follow_redirects=False)
            if r.status_code >= 500:
                errors.append(("/consult POST", r.status_code))
        except Exception as e:
            errors.append(("/consult POST", str(e)))
    return errors

def main():
    print("=== 1. 문법 검사 (모든 .py) ===")
    syn_err = phase1_syntax()
    if syn_err:
        for path, e in syn_err:
            print("FAIL:", path, e)
        sys.exit(1)
    print("OK")

    print("=== 2. 앱 import ===")
    imp_err, app = phase2_import()
    if imp_err:
        print(imp_err)
        sys.exit(1)
    print("OK")

    print("=== 3. 라우트 100회 시뮬레이션 ===")
    route_err = phase3_routes(app, 100)
    if route_err:
        for t in route_err[:20]:
            print("FAIL:", t)
        if len(route_err) > 20:
            print("... 외", len(route_err) - 20, "건")
    else:
        print("OK (100회 x 8 라우트)")

    print("=== 4. POST 안전 50회 ===")
    post_err = phase4_post_safety(app, 50)
    if post_err:
        for t in post_err[:10]:
            print("FAIL:", t)
    else:
        print("OK")

    print("=== 5. 템플릿 렌더 ===")
    tpl_err = phase5_templates(app)
    if tpl_err:
        print("FAIL:", tpl_err)
    else:
        print("OK")

    print("=== 6. policy_import 반환값 ===")
    pi_err = phase6_policy_import_module()
    if pi_err:
        print("FAIL:", pi_err)
    else:
        print("OK")

    print("=== 7. policy_export 빌드 ===")
    exp_err = phase7_policy_export(app)
    if exp_err:
        print("FAIL:", exp_err)
    else:
        print("OK")

    print("=== 8. /consult POST 30회 ===")
    consult_err = phase8_consult_post(app, 30)
    if consult_err:
        for t in consult_err[:5]:
            print("FAIL:", t)
    else:
        print("OK")

    total = len(syn_err) + (1 if imp_err else 0) + len(route_err) + len(post_err) + len(tpl_err) + len(pi_err) + len(exp_err) + len(consult_err)
    if total == 0:
        print("\n=== 전체 검사 통과 ===")
    else:
        print("\n=== 총", total, "건 오류 ===")
        sys.exit(1)

if __name__ == "__main__":
    main()
