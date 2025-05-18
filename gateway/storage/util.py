import sys
import pika, json
import logging
import traceback
import os

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Logger oluştur
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def get_rabbitmq_connection(host="rabbitmq"):
    """RabbitMQ bağlantısı oluştur ve döndür"""
    try:
        # RabbitMQ heartbeat değerini çevre değişkeninden oku
        heartbeat = int(os.environ.get("RABBITMQ_HEARTBEAT", "120"))
        logger.info(f"RabbitMQ bağlantısı oluşturuluyor: {host} (heartbeat: {heartbeat}s)")

        # Bağlantı parametrelerini ayarla
        connection_params = pika.ConnectionParameters(
            host=host,
            port=5672,
            heartbeat=heartbeat,
            blocked_connection_timeout=300,
            socket_timeout=5
        )

        # Bağlantıyı oluştur
        connection = pika.BlockingConnection(connection_params)
        return connection
    except Exception as e:
        logger.error(f"RabbitMQ bağlantı hatası: {e}")
        logger.error(traceback.format_exc())
        raise


def upload(f, fs, channel, access):
    try:
        # Video bilgilerini logla
        if hasattr(f, 'filename'):
            logger.info(
                f"Video dosyası: {f.filename}, MIME type: {f.content_type if hasattr(f, 'content_type') else 'bilinmiyor'}")

        logger.info(f"Video yükleme başlatılıyor: Kullanıcı={access.get('username', 'bilinmiyor')}")

        # GridFS bağlantısını kontrol et
        if fs is None:
            logger.error("GridFS bağlantısı mevcut değil")
            return "GridFS connection error", 500

        fid = fs.put(f)
        logger.info(f"Video MongoDB'ye yüklendi: ID={fid}")
    except Exception as err:
        logger.error(f"MongoDB yükleme hatası: {type(err).__name__}: {err}")
        logger.error(traceback.format_exc())
        return "internal server error", 500

    message = {
        "video_fid": str(fid),
        "mp3_fid": None,
        "username": access.get("username", "bilinmiyor"),
    }

    try:
        # RabbitMQ kanalını kontrol et
        if channel is None or not channel.is_open:
            logger.warning("RabbitMQ kanalı kapalı, yeniden bağlanmaya çalışılıyor...")
            # Eğer kanal kapalıysa, yeni bir bağlantı ve kanal oluştur
            try:
                connection = get_rabbitmq_connection()
                channel = connection.channel()
                # Kuyruğu deklare et
                channel.queue_declare(queue="video", durable=True)
                logger.info("RabbitMQ bağlantısı yeniden kuruldu")
            except Exception as conn_err:
                logger.error(f"RabbitMQ yeniden bağlanma hatası: {conn_err}")
                # Hata durumunda GridFS'ten dosyayı sil
                logger.info(f"Yüklenen video siliniyor: ID={fid}")
                fs.delete(fid)
                return "message queue connection error", 500

        # Kuyruk kontrolü
        try:
            # Kuyruğu pasif modda deklare et (varsa kullan, yoksa hata ver)
            queue_info = channel.queue_declare(queue="video", durable=True, passive=True)
            logger.info(f"RabbitMQ video kuyruğu durumu, Mesaj sayısı: {queue_info.method.message_count}")
        except Exception as queue_err:
            logger.warning(f"Kuyruk durumu kontrol edilemedi: {queue_err}")
            # Kuyruğu aktif olarak deklare et
            channel.queue_declare(queue="video", durable=True)
            logger.info("Video kuyruğu yeniden oluşturuldu")

        logger.info(f"RabbitMQ'ya mesaj gönderiliyor: {message}")
        channel.basic_publish(
            exchange="",
            routing_key="video",
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
            ),
        )
        logger.info("RabbitMQ'ya mesaj başarıyla gönderildi")
    except Exception as err:
        logger.error(f"RabbitMQ gönderme hatası: {type(err).__name__}: {err}")
        logger.error(traceback.format_exc())
        # Hata durumunda GridFS'ten dosyayı sil
        try:
            logger.info(f"Yüklenen video siliniyor: ID={fid}")
            fs.delete(fid)
        except Exception as del_err:
            logger.error(f"Video silinirken hata: {del_err}")
        return "internal server error", 500

    logger.info("Video dönüştürme süreci başarıyla başlatıldı")
    return "success", 200