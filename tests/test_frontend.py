import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def test_frontend_is_a_typed_nextjs_application() -> None:
    package = json.loads((FRONTEND_ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["dependencies"]["next"]
    assert package["dependencies"]["google-auth-library"]
    assert package["scripts"]["typecheck"] == "tsc --noEmit"
    assert (FRONTEND_ROOT / "src/app/page.tsx").is_file()
    assert (FRONTEND_ROOT / "src/app/api/chat/route.ts").is_file()
    assert not (FRONTEND_ROOT / "streamlit_app.py").exists()
    assert not (PROJECT_ROOT / ".streamlit").exists()

    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "FRONTEND_URL=http://localhost:3000" in env_example
    assert "FRONTEND_URL=http://localhost:8501" not in env_example


def test_paid_api_is_reached_only_through_server_route_handlers() -> None:
    client_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FRONTEND_ROOT / "src/components").glob("*.tsx")
    )
    backend_helper = (FRONTEND_ROOT / "src/app/api/_lib/backend.ts").read_text(encoding="utf-8")

    assert 'fetch("/api/chat"' in client_sources
    assert 'fetch("/api/parse-query"' in client_sources
    assert "FIN_RAG_API_BASE" not in client_sources
    assert "getIdTokenClient" in backend_helper
    assert "FIN_RAG_API_BASE" in backend_helper


def test_frontend_container_uses_standalone_non_root_node_runtime() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile.frontend").read_text(encoding="utf-8")

    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "/app/.next/standalone" in dockerfile
    assert "USER nextjs" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "streamlit" not in dockerfile.lower()
