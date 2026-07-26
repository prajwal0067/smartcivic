import os

# Helper to read static files from disk with candidate paths
def read_static_file(filename: str):
    candidate_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename),
        os.path.join(os.getcwd(), "public", filename),
        os.path.join(os.getcwd(), filename),
        os.path.join("/var/task/api/public", filename),
        os.path.join("/var/task/public", filename),
        os.path.join("/var/task", filename),
    ]
    for path in candidate_paths:
        if os.path.exists(path) and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return None
