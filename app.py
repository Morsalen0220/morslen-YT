# app.py (চূড়ান্ত সংস্করণ: সফল এবং ত্রুটি পেজ সহ)
from flask import Flask, request, jsonify, render_template, send_file
import yt_dlp
import os
import urllib.parse
import shutil
import re

# Flask অ্যাপ কনফিগারেশন
app = Flask(__name__)

# ---------------------------------------------------------------------
# **FFmpeg Path নিশ্চিতকরণ**
FFMPEG_EXE_PATH = r'C:\ffmpeg\bin\ffmpeg.exe'  

if not os.path.exists(FFMPEG_EXE_PATH):
    print(f"❌ মারাত্মক সতর্কতা: FFMPEG ফাইলটি এই স্থানে পাওয়া যায়নি: {FFMPEG_EXE_PATH}")
    FFMPEG_EXE_PATH = 'ffmpeg' 
else:
    print(f"✅ FFMPEG ফাইলটি নিশ্চিত করা হলো: {FFMPEG_EXE_PATH}")
# ---------------------------------------------------------------------

# --- নতুন ফাংশন: ফাইলের নাম সরলীকরণ (শুধুমাত্র ভিডিও ID ব্যবহার) ---
def sanitize_filename_simple(video_id, ext):
    """শুধুমাত্র ভিডিও আইডি ব্যবহার করে একটি সাধারণ নাম তৈরি করে।"""
    return f"yt_download_{video_id}.{ext}"

# ----------------- ভিডিও তথ্য পাওয়ার রুট -----------------
@app.route("/get_info", methods=["POST"])
def get_info():
    """ইউটিউব লিঙ্ক থেকে ভিডিওর তথ্য (টাইটেল, কোয়ালিটি, সাইজ) এক্সট্র্যাক্ট করে JSON হিসেবে রিটার্ন করে।"""
    url = request.form.get("url")
    if not url:
        return jsonify({"error": True, "message": "কোনো লিঙ্ক দেওয়া হয়নি"}), 400

    try:
        ydl_opts = {
            'format': 'best', 
            'outtmpl': '%(title)s.%(ext)s',
            'extract_flat': True,
            'skip_download': True,
            'force_generic_extractor': True,
            'noplaylist': True,
            'cachedir': False, 
            'no_warnings': True,
            'ffmpeg_location': FFMPEG_EXE_PATH,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        video_info = info.get('entries', [info])[0] if info.get('entries') else info
        formats = video_info.get('formats', [])
        stream_data = {}

        # --- ১. প্রোগ্রেসিভ স্ট্রিমগুলি যোগ করুন (ভিডিও + অডিও, 360p, 480p) ---
        for f in formats:
            is_progressive = f.get('protocol') == 'https' and f.get('acodec') != 'none' and f.get('vcodec') != 'none' and f.get('ext') == 'mp4' and f.get('height')
            
            if is_progressive and f.get('height') <= 720:
                size_mb = round(f.get('filesize_approx', 0) / (1024 * 1024), 2)
                quality_str = f"{f.get('height')}p"
                
                stream_data[quality_str] = {
                    'id': f['format_id'],
                    'quality': quality_str,
                    'resolution': f.get('height'),
                    'size': f'{size_mb} MB',
                    'ext': f.get('ext'),
                    'type': 'video_progressive'
                }

        # --- ২. অ্যাডাপ্টিভ ভিডিও স্ট্রিমগুলি যোগ করুন (ভিডিও-অনলি, 720p, 1080p, ইত্যাদি) ---
        for f in formats:
            is_adaptive_video = f.get('vcodec') != 'none' and f.get('acodec') == 'none' and f.get('ext') == 'mp4' and f.get('height') > 360
            
            if is_adaptive_video:
                size_mb = round(f.get('filesize_approx', 0) / (1024 * 1024), 2)
                quality_str_key = f"{f.get('height')}p"

                if quality_str_key not in stream_data or stream_data[quality_str_key]['type'] == 'video_progressive': 
                     stream_data[quality_str_key] = {
                        'id': f['format_id'] + '+bestaudio', 
                        'quality': quality_str_key,
                        'resolution': f.get('height'),
                        'size': f'{size_mb} MB (Video Only)',
                        'ext': f.get('ext'),
                        'type': 'video_adaptive_merge'
                    }

        # --- ৩. অডিও অপশনগুলি যোগ করা ---
        audio_streams = [f for f in formats if f.get('vcodec') == 'none' and f.get('ext') in ('m4a', 'mp3', 'webm')]
        if audio_streams:
            best_audio = max(audio_streams, key=lambda x: x.get('abr', 0))
            size_mb = round(best_audio.get('filesize_approx', 0) / (1024 * 1024), 2)

            # MP3 কনভার্সন অপশন (FFmpeg প্রয়োজন)
            stream_data['mp3_convert'] = {
                'id': 'mp3_convert',
                'quality': 'Audio (MP3)',
                'resolution': 0,
                'size': f'{size_mb} MB (approx)',
                'ext': 'mp3',
                'type': 'audio_convert'
            }

        final_streams = list(stream_data.values())
        final_streams.sort(key=lambda x: x.get('resolution', 0), reverse=True)


        return jsonify({
            "error": False,
            "title": video_info.get('title'),
            "thumbnail": video_info.get('thumbnail'),
            "channel": video_info.get('channel'),
            "duration": video_info.get('duration_string'),
            "streams": final_streams
        })

    except Exception as e:
        print(f"❌ ভিডিও তথ্য পেতে মারাত্মক ত্রুটি: {str(e)}")
        return jsonify({"error": True, "message": f"ভিডিও তথ্য পেতে ব্যর্থ। লিঙ্কটি সঠিক কিনা নিশ্চিত করুন। \nবিস্তারিত: {str(e)}"}), 500


# ----------------- ডাউনলোড হ্যান্ডেল করার রুট -----------------
@app.route("/download/<stream_id>", methods=["GET"])
def download_stream(stream_id):
    """ক্লিকের পর নির্দিষ্ট কোয়ালিটির ফাইলটি ডাউনলোড করে এবং ফাইলটিকে সার্ভ করে।"""
    url = request.args.get('url')
    ext = request.args.get('ext')
    raw_title = urllib.parse.unquote(request.args.get('title'))
    
    if not url or not ext or not raw_title:
        return render_template('error.html', message='ডাউনলোড করার জন্য প্রয়োজনীয় ডেটা খুঁজে পাওয়া যায়নি।'), 400

    # ভিডিও ID বের করা
    video_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('v', [None])[0]
    if not video_id:
        return render_template('error.html', message='ভিডিও আইডি খুঁজে পাওয়া যায়নি।'), 400
    
    # ফাইলের নাম সরলীকরণ
    simplified_filename = sanitize_filename_simple(video_id, ext)

    try:
        download_dir = os.path.join(os.getcwd(), 'downloads')
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        # ফাইল তৈরি করার জন্য yt-dlp কে সরলীকৃত আউটপুট টেমপ্লেট দেওয়া হলো
        output_template = os.path.join(download_dir, simplified_filename)
        
        ydl_opts = {
            'outtmpl': output_template,
            'ignoreerrors': True,
            'force_overwrite': True,
            'merge_output_format': 'mp4', 
            'ffmpeg_location': FFMPEG_EXE_PATH,
        }

        if stream_id == 'mp3_convert':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(download_dir, sanitize_filename_simple(video_id, 'mp3'))
            })
        elif '+bestaudio' in stream_id: 
             ydl_opts.update({'format': stream_id})
        else:
            ydl_opts.update({'format': stream_id})
        
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Starting download for {video_id} using FFMPEG at: {FFMPEG_EXE_PATH}")
            # --- ডাউনলোড শুরু ---
            info = ydl.extract_info(url, download=True)
            # --- ডাউনলোড শেষ ---

        
        # ডাউনলোডকৃত ফাইলের নাম চূড়ান্ত করা
        if 'mp3_convert' in stream_id:
            final_file_name = os.path.join(download_dir, sanitize_filename_simple(video_id, 'mp3'))
        elif '+bestaudio' in stream_id:
             final_file_name = os.path.join(download_dir, sanitize_filename_simple(video_id, 'mp4'))
        else:
             final_file_name = os.path.join(download_dir, sanitize_filename_simple(video_id, ext))
        
        
        # ফাইলটি খুঁজে বের করার জন্য অতিরিক্ত চেক
        found_final_file = False
        if not os.path.exists(final_file_name):
            for file_ext in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a']:
                temp_name = os.path.join(download_dir, f'yt_download_{video_id}.{file_ext}')
                if os.path.exists(temp_name):
                    final_file_name = temp_name
                    found_final_file = True
                    break

        if os.path.exists(final_file_name) or found_final_file:
            
            response = send_file(final_file_name, 
                                 as_attachment=True, 
                                 download_name=f'{raw_title}.{ext}', 
                                 mimetype=f'audio/{ext}' if ext in ['mp3', 'm4a'] else f'video/{ext}')
            
            # ডাউনলোড শেষ হওয়ার পর সার্ভার থেকে ফাইলটি মুছে ফেলার লজিক
            @response.call_on_close
            def cleanup():
                if os.path.exists(final_file_name):
                    os.remove(final_file_name)
                    
            # 💡 এখানে আমরা আর কোনো রিডাইরেক্ট করছি না, বরং ফাইল সার্ভ করছি
            return response
        else:
            print(f"❌ ফাইল খোঁজা ব্যর্থ: আউটপুট ফাইলটি তৈরি হয়নি বা খুঁজে পাওয়া যায়নি: {final_file_name}")
            return render_template('error.html', message='ডাউনলোড ব্যর্থ হয়েছে: ফাইল সার্ভার তৈরি করতে পারেনি।'), 500

    except Exception as e:
        print(f"❌ মারাত্মক ডাউনলোড ত্রুটি: {str(e)}")
        return render_template('error.html', message=f'অপ্রত্যাশিত সার্ভার ত্রুটি: {str(e)}'), 500


# ----------------- নতুন রুট: সাফল্যের পরে রিডাইরেক্ট -----------------
@app.route("/success")
def success():
    # সাফল্যের পেজটি দেখান
    return render_template('success.html')

# ----------------- রুট পেজ -----------------
@app.route("/")
def index():
    """index.html ফাইলটিকে সার্ভ করে"""
    return render_template("index.html")

# ----------------- ত্রুটি হ্যান্ডলিং পেজ -----------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', message="পেজটি খুঁজে পাওয়া যায়নি (404 Error)"), 404


if __name__ == "__main__":
    # Flask অ্যাপ চালান
    app.run(debug=True)
