from flask import Flask

from backend.routes import register_routes

app = Flask(__name__)

# النظام كله عربي، وFlask افتراضيًا بيهرّب كل حرف عربي لـ\uXXXX في الـJSON
# — ده بيكبّر كل استجابة لأكتر من الضعف على الفاضي. UTF-8 مباشرة أصغر وأسرع.
app.json.ensure_ascii = False

register_routes(app)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "5000"))
    print(f"Personnel System running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
