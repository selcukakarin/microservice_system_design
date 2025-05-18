
import pika, sys, os, time
from pymongo import MongoClient
import gridfs
from convert import to_mp3
import logging
import traceback

# Loglama ayarları
logging.basicConfig(
    level=logging.DEBUG if os.environ.get("LOG_LEVEL") == "DEBUG" else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def main():
    # Çevre değişkenlerinden yapılandırmaları al
    mongodb_host = os.environ.get("MONGODB_HOST", "mongodb")

    # MONGODB_PORT değişkenini kontrol et - URL formatında gelebilir
    try:
        mongodb_port_raw = os.environ.get("MONGODB_PORT", "27017")
        # Eğer port bir URL ise, sadece sayı kısmını çıkar
        if "://" in mongodb_port_raw:
            # URL formatında geldi, port numarasını çıkar
            mongodb_port = int(mongodb_port_raw.split(":")[-1])
            logger.warning(
                f"MONGODB_PORT URL formatında ({mongodb_port_raw}), sadece port numarası alındı: {mongodb_port}")
        else:
            # Normal format
            mongodb_port = int(mongodb_port_raw)
    except ValueError as e:
        logger.error(f"MONGODB_PORT değeri geçersiz ({mongodb_port_raw}): {str(e)}")
        logger.error("Varsayılan 27017 portu kullanılacak")
        mongodb_port = 27017

    rabbitmq_host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    # RabbitMQ heartbeat değerini çevre değişkeninden oku
    rabbitmq_heartbeat = int(os.environ.get("RABBITMQ_HEARTBEAT", "120"))
    video_queue = os.environ.get("VIDEO_QUEUE", "video")
    mp3_queue = os.environ.get("MP3_QUEUE", "mp3")

    logger.info(f"Yapılandırma: MongoDB={mongodb_host}:{mongodb_port}, RabbitMQ={rabbitmq_host} (heartbeat: {rabbitmq_heartbeat}s), "
                f"VideoQueue={video_queue}, MP3Queue={mp3_queue}")

    # MongoDB bağlantısı
    try:
        client = MongoClient(mongodb_host, mongodb_port, serverSelectionTimeoutMS=5000)
        # Bağlantıyı test et
        client.admin.command('ping')
        logger.info("MongoDB bağlantısı başarılı")

        db_videos = client.videos
        db_mp3s = client.mp3s
        # gridfs
        fs_videos = gridfs.GridFS(db_videos)
        fs_mp3s = gridfs.GridFS(db_mp3s)
    except Exception as e:
        logger.error(f"MongoDB bağlantı hatası: {e}")
        logger.error(traceback.format_exc())

        # MongoDB URI formatını deneyelim
        try:
            logger.info("MongoDB URI formatı deneniyor...")
            uri = f"mongodb://{mongodb_host}:{mongodb_port}/"
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            logger.info(f"MongoDB URI bağlantısı başarılı: {uri}")

            db_videos = client.videos
            db_mp3s = client.mp3s
            fs_videos = gridfs.GridFS(db_videos)
            fs_mp3s = gridfs.GridFS(db_mp3s)
        except Exception as uri_e:
            logger.error(f"MongoDB URI bağlantı hatası: {uri_e}")
            logger.error(traceback.format_exc())
            sys.exit(1)

    # RabbitMQ bağlantısı
    connection = None
    channel = None

    # Bağlantı tekrar deneme mantığı
    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:
        try:
            logger.info(f"RabbitMQ bağlantısı kuruluyor: {rabbitmq_host} (heartbeat: {rabbitmq_heartbeat}s)")

            # RabbitMQ bağlantı parametrelerini güncelle
            connection_params = pika.ConnectionParameters(
                host=rabbitmq_host,
                port=5672,
                heartbeat=rabbitmq_heartbeat,  # Değişiklik burada: heartbeat değeri çevre değişkeninden
                blocked_connection_timeout=300,
                socket_timeout=5  # Soket zaman aşımı ekle
            )

            connection = pika.BlockingConnection(connection_params)
            channel = connection.channel()

            # Queue'ları deklare et
            channel.queue_declare(queue=video_queue, durable=True)
            channel.queue_declare(queue=mp3_queue, durable=True)

            logger.info("RabbitMQ bağlantısı başarılı")
            break
        except Exception as e:
            retry_count += 1
            wait_time = 5 * retry_count  # Beklenecek süreyi artır

            logger.error(f"RabbitMQ bağlantı hatası (Deneme {retry_count}/{max_retries}): {e}")

            if retry_count >= max_retries:
                logger.error("Maksimum deneme sayısına ulaşıldı. Çıkılıyor.")
                sys.exit(1)

            logger.info(f"{wait_time} saniye sonra tekrar deneniyor...")
            time.sleep(wait_time)

    def callback(ch, method, properties, body):
        try:
            logger.info("Mesaj alındı, işleniyor...")

            # to_mp3.py'deki start fonksiyonunu çağır
            err = to_mp3.start(body, fs_videos, fs_mp3s, ch)

            if err:
                logger.error(f"Dönüştürme hatası: {err}")
                ch.basic_nack(delivery_tag=method.delivery_tag)
            else:
                logger.info("Dönüştürme başarılı, mesaj onaylandı")
                ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error(f"Callback hatası: {e}")
            logger.error(traceback.format_exc())
            # Mesajı yeniden kuyruğa ekle
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    # Aynı anda yalnızca bir mesaj işle
    channel.basic_qos(prefetch_count=1)

    # Mesaj tüketmeye başla
    channel.basic_consume(
        queue=video_queue, on_message_callback=callback
    )

    logger.info(f"Mesajlar bekleniyor. Çıkmak için CTRL+C tuşuna basın.")

    try:
        # Periyodik olarak bağlantı durumunu kontrol et
        def health_check():
            while True:
                try:
                    time.sleep(30)  # 30 saniyede bir kontrol et
                    # RabbitMQ bağlantısı açık mı kontrol et
                    if connection and connection.is_open:
                        logger.debug("Bağlantı durumu kontrol edildi - RabbitMQ bağlantısı açık")
                    else:
                        logger.warning("RabbitMQ bağlantısı kapalı, yeniden bağlanılıyor...")
                        # Burada yeniden bağlanma mantığı eklenebilir
                        break
                except Exception as e:
                    logger.error(f"Health check hatası: {e}")
                    break

        # Sağlık kontrolünü ayrı bir thread'de çalıştır
        import threading
        health_thread = threading.Thread(target=health_check, daemon=True)
        health_thread.start()

        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu")
        channel.stop_consuming()
    except Exception as e:
        logger.error(f"Beklenmeyen hata: {e}")
        logger.error(traceback.format_exc())
    finally:
        if connection and connection.is_open:
            connection.close()
            logger.info("RabbitMQ bağlantısı kapatıldı")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)