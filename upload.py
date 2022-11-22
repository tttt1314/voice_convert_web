from flask import Flask, render_template, request
import os
import soundfile as sf
import io
import numpy as np
from six.moves.urllib.request import urlopen
from convert_realtime import web_voice_convert 
app = Flask(__name__)
app.config["UPLOAD_DIR"] = "./static/uploads"


@app.route("/", methods=["GET", "POST"])
def upload():
    if request.method == 'POST':
        file = request.files['file']
        in_path = os.path.join(app.config['UPLOAD_DIR'], file.filename)
        out_path = "./static/converted"
        file.save(in_path)
        data, samplerate = sf.read(in_path)
        sf.write('input_file.wav', data, samplerate,
             format='wav')
        web_voice_convert('input_file.wav', out_path  )
        return render_template("results.html", in_path=in_path, out_path = out_path)
    return render_template("upload.html", msg="")


if __name__ == "__main__":
    app.run()
