import json

from app.core.config import PROJECT_ROOT
from app.main import create_app

app = create_app()
try:
    (PROJECT_ROOT / "frontend/openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
finally:
    app.state.engine.dispose()
