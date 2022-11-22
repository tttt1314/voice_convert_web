from flask import Flask, render_template, request
import convert_realtime
from flask import request
import os
import soundfile as sf
import io
import numpy as np
from six.moves.urllib.request import urlopen
from flask import send_file
app = Flask(__name__)
app.config["UPLOAD_DIR"] = "uploads"
@app.route('/')
def root():
    if request.method == 'POST':
        file = request.files['file']
        file.save(os.path.join(app.config['UPLOAD_DIR'], file.filename))
        return render_template("upload.html", msg="File uplaoded successfully.")
    return render_template("upload.html", msg="")

@app.route('/audioUpload1', methods=["POST"])
def audioUpload2():
    f = request.files['audio-file']
    print(f)
    out_url = "../client/src/converted_audio/"

    convert_realtime.web_voice_convert(in_url=f, out_url=out_url)
    return "done!"


@app.route('/audioUpload')
def view_method():
    path_to_file = "/test.wav"

    return send_file(
        path_to_file,
        mimetype="audio/wav",
        as_attachment=True,
        attachment_filename="test.wav")

@app.route('/audioUpload0', methods=['POST'])
def audioUpload():
    f = request.files['audio-file']
    print(f)
    #f.save(os.path.join(app.config['UPLOAD_DIR'], f.filename))
    data, samplerate = sf.read(io.BytesIO(urlopen(f).read()))
    sf.write('stereo_file.flac', data, samplerate,
        format='flac', subtype='PCM_24')
    return "done"
'''
@app.route('/getname',method=['GET'])
def getname():
    name = request.args.get('name')
    return render_template('get.html',**locals())
'''
if __name__ == '__main__':
    app.run(debug=True)
