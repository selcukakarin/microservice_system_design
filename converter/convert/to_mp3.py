import pika, json, tempfile, os
from bson.objectid import ObjectId
import moviepy.editor
import logging
import traceback

logger = logging.getLogger(__name__)


def start(message, fs_videos, fs_mp3s, channel, mp3_queue=None):
    """
    Video dosyasını MP3'e dönüştür ve sonucu MongoDB ve RabbitMQ'ya gönder

    Args:
        message: JSON formatında dönüştürülecek video mesajı
        fs_videos: Video GridFS nesnesi
        fs_mp3s: MP3 GridFS nesnesi
        channel: RabbitMQ kanal nesnesi
        mp3_queue: MP3 kuyruğunun adı (None ise çevre değişkeninden alınır)

    Returns:
        Hata oluşursa hata mesajı, yoksa None
    """
    try:
        # Mesajı JSON formatına dönüştür
        if isinstance(message, bytes):
            message = message.decode('utf-8')

        message = json.loads(message)
        video_fid = message["video_fid"]

        logger.info(f"Video ID: {video_fid} dönüştürülüyor")

        # Geçici dosya oluştur
        tf = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        tf_path = tf.name

        try:
            # GridFS'den video içeriğini al
            out = fs_videos.get(ObjectId(video_fid))

            # Video içeriğini geçici dosyaya yaz
            tf.write(out.read())
            tf.close()

            logger.info(f"Video dosyası geçici konuma yazıldı: {tf_path}")

            # Video dosyasından ses içeriğini çıkar
            video = moviepy.editor.VideoFileClip(tf_path)
            audio = video.audio

            if audio is None:
                logger.warning("Videoda ses yok!")
                return "Video contains no audio"

            # MP3 dosyasını kaydet
            mp3_path = tempfile.gettempdir() + f"/{video_fid}.mp3"
            logger.info(f"MP3 dosyası oluşturuluyor: {mp3_path}")

            audio.write_audiofile(mp3_path, logger=None)
            video.close()

            logger.info(f"MP3 dosyası oluşturuldu: {mp3_path}")

            # MP3 dosyasını GridFS'e kaydet
            with open(mp3_path, "rb") as f:
                data = f.read()
                mp3_id = fs_mp3s.put(data, filename=f"{video_fid}.mp3")
                logger.info(f"MP3 dosyası MongoDB'ye kaydedildi. ID: {mp3_id}")

            # Geçici dosyaları temizle
            try:
                os.remove(tf_path)
                os.remove(mp3_path)
                logger.info("Geçici dosyalar temizlendi")
            except Exception as e:
                logger.warning(f"Geçici dosya temizleme hatası: {e}")

            # MP3 ID'sini mesaja ekle
            message["mp3_fid"] = str(mp3_id)

            # Kullanılacak MP3 kuyruğunu belirle
            if mp3_queue is None:
                mp3_queue = os.environ.get("MP3_QUEUE")

            logger.info(f"MP3 dönüştürme tamamlandı, '{mp3_queue}' kuyruğuna mesaj gönderiliyor")

            # RabbitMQ'ya mesaj gönder
            channel.basic_publish(
                exchange="",
                routing_key=mp3_queue,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
                ),
            )

            logger.info("Mesaj başarıyla gönderildi")
            return None

        except Exception as err:
            error_message = str(err)
            logger.error(f"MP3 dönüştürme hatası: {error_message}")
            logger.error(traceback.format_exc())

            # Hata durumunda mesajı RabbitMQ'ya göndermeyin ve GridFS'deki MP3'ü silin
            if 'mp3_id' in locals():
                try:
                    logger.info(f"Hata nedeniyle MP3 dosyası siliniyor. ID: {mp3_id}")
                    fs_mp3s.delete(mp3_id)
                except Exception as delete_err:
                    logger.error(f"MP3 silme hatası: {delete_err}")

            # Geçici dosyaları temizle
            for path in [tf_path, tempfile.gettempdir() + f"/{video_fid}.mp3"]:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as rm_err:
                    logger.warning(f"Geçici dosya temizleme hatası: {rm_err}")

            return f"Dönüştürme hatası: {error_message}"

    except Exception as e:
        error_message = str(e)
        logger.error(f"Beklenmeyen hata: {error_message}")
        logger.error(traceback.format_exc())
        return f"Beklenmeyen hata: {error_message}"