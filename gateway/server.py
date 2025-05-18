import os, gridfs, pika, json
import sys

from flask import Flask, request, send_file
from flask_pymongo import PyMongo
from auth import validate
from auth_svc import access
from storage import util
from bson.objectid import ObjectId

import logging

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Logging'i yapılandır
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

server = Flask(__name__)

# MongoDB bağlantı adreslerini Kubernetes servis adı ile güncelle
mongodb_host = os.environ.get("MONGODB_HOST", "mongodb")  # Çevre değişkeni veya varsayılan değer
logger.info(f"MongoDB host: {mongodb_host}")

mongo_video = PyMongo(server, uri=f"mongodb://{mongodb_host}:27017/videos")
mongo_mp3 = PyMongo(server, uri=f"mongodb://{mongodb_host}:27017/mp3s")

fs_videos = gridfs.GridFS(mongo_video.db)
fs_mp3s = gridfs.GridFS(mongo_mp3.db)

connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
channel = connection.channel()


@server.route("/login", methods=["POST"])
def login():
    token, err = access.login(request)

    if not err:
        return token
    else:
        return err


@server.route("/upload", methods=["POST"])
def upload():
    print("selcuk - başlangıç")
    sys.stdout.flush()

    logger.info("selcuk")
    logger.debug("Upload endpoint hit")

    access, err = validate.token(request)

    if err:
        logger.error(f"Validation error: {err}")
        return err
    print("Token doğrulaması başarılı")
    sys.stdout.flush()

    access = json.loads(access)

    if access["admin"]:
        if len(request.files) > 1 or len(request.files) < 1:
            print("Dosya sayısı hatası: Tam olarak 1 dosya gerekli")
            sys.stdout.flush()

            return "exactly 1 file required", 400

        for _, f in request.files.items():
            print(f"Dosya yükleniyor: {f.filename}")
            sys.stdout.flush()

            err = util.upload(f, fs_videos, channel, access)

            if err:
                print(f"Yükleme hatası: {err}")
                sys.stdout.flush()

                return err

        print("Yükleme başarılı!")
        sys.stdout.flush()

        return "success!", 200
    else:
        print("Yetkilendirme hatası: Yönetici değil")
        sys.stdout.flush()

        return "not authorized", 401


@server.route("/download", methods=["GET"])
def download():
    access, err = validate.token(request)

    if err:
        return err

    access = json.loads(access)

    if access["admin"]:
        fid_string = request.args.get("fid")

        if not fid_string:
            return "fid is required", 400

        try:
            out = fs_mp3s.get(ObjectId(fid_string))
            return send_file(out, download_name=f"{fid_string}.mp3")
        except Exception as err:
            print(err)
            return "internal server error", 500

    return "not authorized", 401


if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8080, debug=True)