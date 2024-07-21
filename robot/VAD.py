import collections
import logging
import os
import pyaudio
import time
from contextlib import contextmanager
from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from robot import logging
from robot import constants
import wave
import webrtcvad

logger = logging.getLogger("vad")

def py_error_handler(filename, line, function, err, fmt):
    pass

ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
TOP_DIR = os.path.dirname(os.path.abspath(__file__))

DETECT_DING = os.path.join(TOP_DIR, "resources/ding.wav")
DETECT_DONG = os.path.join(TOP_DIR, "resources/dong.wav")

SAMPLE_RATE = 16000
CHANNEL_NUMS = 1
BIT_WIDTH = 2

@contextmanager
def no_alsa_error():
    try:
        asound = cdll.LoadLibrary("libasound.so")
        asound.snd_lib_error_set_handler(c_error_handler)
        yield
        asound.snd_lib_error_set_handler(None)
    except:
        yield
        pass

class RingBuffer(object):
    """Ring buffer to hold audio from PortAudio"""

    def __init__(self, size=4096):
        self._buf = collections.deque(maxlen=size)

    def extend(self, data):
        """Adds data to the end of buffer"""
        self._buf.extend(data)

    def get(self):
        """Retrieves data from the beginning of buffer and clears it"""
        tmp = bytes(bytearray(self._buf))
        self._buf.clear()
        return tmp

class VADListener(object):
    """Listening with VAD"""

    def __init__(self):
        logger.debug("activeListen __init__()")
        self.recordedData = []
        self.vad = webrtcvad.Vad(3)
        # https://github.com/wiseman/py-webrtcvad/tree/master
        # sample_rate: 16000 frame: 10ms bit_width: 2
        # buffer = sample_rate * bit_width * frame / 1000 = 320
        self.ring_buffer = RingBuffer(size=320)

    def listen(
        self,
        interrupt_check=lambda: False,
        silent_timeout=3,
        recording_timeout=15,
    ):
        """
        :param interrupt_check: a function that returns True if the main loop
                                needs to stop.
        :param silent_timeout: indicates how long silence must be heard
                                       to mark the end of a phrase that is
                                       being recorded.
        :param recording_timeout: limits the maximum length of a recording.
        :return: recorded file path
        """
        logger.debug("activeListen listen()")
        silent_threshold = 100 * silent_timeout
        recording_threshold = 100 * recording_timeout

        sleep_time=0.01 # 10ms
        self._running = True

        def audio_callback(in_data, frame_count, time_info, status):
            self.ring_buffer.extend(in_data)
            play_data = chr(0) * len(in_data)
            return play_data, pyaudio.paContinue

        with no_alsa_error():
            self.audio = pyaudio.PyAudio()

        logger.debug("opening audio stream")

        try:
            self.stream_in = self.audio.open(
                input=True,
                output=False,
                format=self.audio.get_format_from_width(BIT_WIDTH),
                channels=1,
                rate=SAMPLE_RATE,
                frames_per_buffer=160, # sample_size / 1000 * 10
                stream_callback=audio_callback,
            )
        except Exception as e:
            logger.critical(e, stack_info=True)
            return

        logger.debug("audio stream opened")

        if interrupt_check():
            logger.debug("detect voice return")
            return

        silentCount = 0
        recordingCount = 0

        logger.debug("begin activeListen loop")

        while self._running is True:

            if interrupt_check():
                logger.debug("detect voice break")
                break
            data = self.ring_buffer.get()
            if len(data) == 0:
                time.sleep(sleep_time)
                continue
            
            status = self.vad.is_speech(data, SAMPLE_RATE)
            if status is None:
                logger.warning("Error initializing streams or reading audio data")

            stopRecording = False
            if recordingCount > recording_threshold:
                stopRecording = True
            elif not status:  # silence found
                if silentCount > silent_threshold:
                    stopRecording = True
                else:
                    silentCount = silentCount + 1
            elif status:  # voice found
                silentCount = 0

            if stopRecording == True:
                return self.saveMessage()

            recordingCount = recordingCount + 1
            self.recordedData.append(data)

        logger.debug("finished.")

    def saveMessage(self):
        """
        Save the message stored in self.recordedData to a timestamped file.
        """
        filename = os.path.join(
            constants.TEMP_PATH, "output" + str(int(time.time())) + ".wav"
        )
        data = b"".join(self.recordedData)

        # use wave to save data
        wf = wave.open(filename, "wb")
        wf.setnchannels(CHANNEL_NUMS)
        wf.setsampwidth(
            self.audio.get_sample_size(
                self.audio.get_format_from_width(BIT_WIDTH)
            )
        )
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data)
        wf.close()
        logger.debug("finished saving: " + filename)

        self.stream_in.stop_stream()
        self.stream_in.close()
        self.audio.terminate()

        return filename