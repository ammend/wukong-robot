import time

from robot import config, logging, utils, constants

logger = logging.getLogger(__name__)

detector = None
recorder = None
porcupine = None


def initDetector(wukong):
    """
    only support porcupine
    """
    global porcupine, recorder, detector
    import pvporcupine
    from pvrecorder import PvRecorder

    access_key = config.get("/porcupine/access_key")
    keyword_paths = config.get("/porcupine/keyword_paths")
    keywords = config.get("/porcupine/keywords", ["porcupine"])
    if keyword_paths:
        porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[constants.getConfigData(kw) for kw in keyword_paths],
            sensitivities=[config.get("sensitivity", 0.5)] * len(keyword_paths),
        )
    else:
        porcupine = pvporcupine.create(
            access_key=access_key,
            keywords=keywords,
            sensitivities=[config.get("sensitivity", 0.5)] * len(keywords),
        )

    recorder = PvRecorder(device_index=-1, frame_length=porcupine.frame_length)
    recorder.start()

    try:
        while True:
            pcm = recorder.read()

            result = porcupine.process(pcm)
            if result >= 0:
                kw = keyword_paths[result] if keyword_paths else keywords[result]
                logger.info(
                    "[porcupine] Keyword {} Detected at time {}".format(
                        kw,
                        time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(time.time())
                        ),
                    )
                )
                wukong._detected_callback(False)
                recorder.stop()
                wukong.conversation.interrupt()
                query = wukong.conversation.activeListen()
                wukong.conversation.doResponse(query)
                recorder.start()
    except pvporcupine.PorcupineActivationError as e:
        logger.error("[Porcupine] AccessKey activation error", stack_info=True)
        raise e
    except pvporcupine.PorcupineActivationLimitError as e:
        logger.error(
            f"[Porcupine] AccessKey {access_key} has reached it's temporary device limit",
            stack_info=True,
        )
        raise e
    except pvporcupine.PorcupineActivationRefusedError as e:
        logger.error(
            "[Porcupine] AccessKey '%s' refused" % access_key, stack_info=True
        )
        raise e
    except pvporcupine.PorcupineActivationThrottledError as e:
        logger.error(
            "[Porcupine] AccessKey '%s' has been throttled" % access_key,
            stack_info=True,
        )
        raise e
    except pvporcupine.PorcupineError as e:
        logger.error("[Porcupine] 初始化 Porcupine 失败", stack_info=True)
        raise e
    except KeyboardInterrupt:
        logger.info("Stopping ...")
    finally:
        porcupine and porcupine.delete()
        recorder and recorder.delete()