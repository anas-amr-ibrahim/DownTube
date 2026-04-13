from flask import Flask, render_template, request, url_for, send_file, jsonify, redirect
import yt_dlp
import os
import uuid
import threading
import time
import re


# Demo credentials (matches the hint in login page)
UserName = "anas"
Password = "123"

app = Flask(__name__)

# Create downloads folder
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Store download progress and completion status
progress_data = {}
download_ready = {}  # file_id -> bool


# =========================
# 🔐 AUTHENTICATION ROUTES
# =========================

@app.route("/")
def home():
    return redirect(url_for("index"))


@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/registerd", methods=["POST"])
def register():
    username = request.form.get("username")
    password = request.form.get("password")
    
    if username == UserName and password == Password:
        return render_template("success.html")
    elif username != UserName and password != Password:
        return render_template("failure.html", message="username & password")
    elif username != UserName:
        return render_template("failure.html", message="username")
    elif password != Password:
        return render_template("failure.html", message="password")
    else:
        return render_template("failure.html", message="unknown error")


# =========================
# 🎬 VIDEO SEARCH & DOWNLOAD
# =========================

@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "POST":
        url = request.form.get("url")
        try:
            data = extract_info(url)
            return render_template(
                "search.html",
                formats=data["formats"],
                url=url,
                title=data["title"],
                thumbnail=data["thumbnail"],
                error=None
            )
        except Exception as e:
            return render_template(
                "search.html",
                formats=None,
                url=None,
                title=None,
                thumbnail=None,
                error="Invalid URL or unable to fetch video info."
            )
    
    return render_template("search.html", formats=None, error=None)



def extract_info(url):
    """Extract video information without downloading"""
    ydl_opts = {'quiet': True}
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        formats = []
        for f in info.get("formats", []):
            if f.get("vcodec") != "none":  # Only video formats
                formats.append({
                    "id": f["format_id"],
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution") or "unknown",
                    "has_audio": f.get("acodec") != "none"
                })
        
        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "formats": formats
        }


def progress_hook(d, file_id):
    """Track download progress (before merging)"""
    if d['status'] == 'downloading':
        percent_str = d.get('_percent_str', '0%').strip()
        progress_data[file_id] = percent_str
    elif d['status'] == 'finished':
        # Download finished, but merging may still happen
        progress_data[file_id] = "100%"
        # Don't set ready yet – wait for postprocessor


def postprocessor_hook(d, file_id):
    """Called after ffmpeg merging is complete"""
    if d['status'] == 'finished':
        # This means post-processing (merging) is done
        download_ready[file_id] = True


@app.route("/start_download", methods=["POST"])
def start_download():
    """Start background download thread"""
    url = request.form.get("url")
    format_id = request.form.get("format_id")
    
    file_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_FOLDER, f"{file_id}.mp4")
    
    progress_data[file_id] = "0%"
    download_ready[file_id] = False
    
    def download():
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best",
            "outtmpl": output_path,
            "merge_output_format": "mp4",
            "progress_hooks": [lambda d: progress_hook(d, file_id)],
            "postprocessor_hooks": [lambda d: postprocessor_hook(d, file_id)],
            "quiet": True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    
    threading.Thread(target=download).start()
    return jsonify({"file_id": file_id})


@app.route("/progress/<file_id>")
def progress(file_id):
    """Return current download progress"""
    return jsonify({"progress": progress_data.get(file_id, "0%")})


@app.route("/ready/<file_id>")
def ready(file_id):
    """Return whether the final file exists and is ready to download"""
    path = os.path.join(DOWNLOAD_FOLDER, f"{file_id}.mp4")
    is_ready = download_ready.get(file_id, False) and os.path.exists(path)
    return jsonify({"ready": is_ready})


@app.route("/download/<file_id>")
def download_file(file_id):
    """Serve the downloaded file and schedule deletion"""
    path = os.path.join(DOWNLOAD_FOLDER, f"{file_id}.mp4")
    
    # Double-check the file exists
    if not os.path.exists(path):
        return "File not found. The download may not have completed.", 404
    
    def remove_file():
        time.sleep(10)  # Wait 10 seconds before deleting
        try:
            if os.path.exists(path):
                os.remove(path)
            # Clean up progress and ready entries
            if file_id in progress_data:
                del progress_data[file_id]
            if file_id in download_ready:
                del download_ready[file_id]
        except Exception:
            pass
    
    response = send_file(path, as_attachment=True)
    threading.Thread(target=remove_file).start()
    return response


if __name__ == "__main__":
    app.run(debug=True, threaded=True)