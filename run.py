# run.py
from app import create_app

app = create_app()

# --- DEBUG: imprime todas las rutas registradas ---
print("\n=== RUTAS REGISTRADAS ===")
for rule in app.url_map.iter_rules():
    print(f"{rule.endpoint:40s} {rule.rule}")
print("=========================\n")
# --- FIN DEBUG ---

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)