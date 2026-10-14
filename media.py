import asyncio
import fractions
import queue
import threading
import uuid

import av
import cv2
import numpy as np
import sounddevice as sd
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    AudioStreamTrack,
    VideoStreamTrack,
)
from aiortc.mediastreams import MediaStreamError


class _CameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError('Could not open the default camera.')

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ok, image = await asyncio.to_thread(self.capture.read)
        if not ok:
            raise MediaStreamError
        frame = av.VideoFrame.from_ndarray(image, format='bgr24')
        frame.pts = pts
        frame.time_base = time_base
        return frame

    def stop(self):
        if self.capture.isOpened():
            self.capture.release()
        super().stop()


class _MicrophoneTrack(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self.frames = queue.Queue(maxsize=20)

        def capture(indata, frame_count, time_info, status):
            frame = indata.copy()
            try:
                self.frames.put_nowait(frame)
            except queue.Full:
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                self.frames.put_nowait(frame)

        self.stream = sd.InputStream(
            samplerate=48000,
            channels=1,
            dtype='int16',
            blocksize=960,
            callback=capture,
        )
        self.stream.start()
        self.pts = 0

    async def recv(self):
        data = await asyncio.to_thread(self.frames.get)
        samples = np.ascontiguousarray(data.T)
        frame = av.AudioFrame.from_ndarray(samples, format='s16', layout='mono')
        frame.sample_rate = 48000
        frame.pts = self.pts
        frame.time_base = fractions.Fraction(1, 48000)
        self.pts += frame.samples
        return frame

    def stop(self):
        if self.stream.active:
            self.stream.stop()
        self.stream.close()
        super().stop()


class CallManager:
    def __init__(self, send_signal, on_status, on_video_frame):
        self.send_signal = send_signal
        self.on_status = on_status
        self.on_video_frame = on_video_frame
        self.call_id = None
        self.peer = None
        self.video = False
        self.pc = None
        self.ring_timer = None
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def start_call(self, peer, video):
        if self.call_id is not None:
            self.on_status('A call is already active.', peer)
            return
        self.call_id = uuid.uuid4().hex
        self.peer = peer
        self.video = bool(video)
        self.on_status(f'Calling {peer}...', peer)
        self.loop.call_soon_threadsafe(self._start_ring_timeout, self.call_id)
        asyncio.run_coroutine_threadsafe(self._create_offer(), self.loop)

    def _start_ring_timeout(self, call_id):
        self.ring_timer = self.loop.call_later(45, self._expire_ringing, call_id)

    def _expire_ringing(self, call_id):
        if self.call_id == call_id and self.pc is not None and self.pc.remoteDescription is None:
            self.send_signal(self.peer, call_id, 'hangup')
            asyncio.create_task(self._close_call('No answer. Call ended.'))

    def handle_signal(self, message):
        if not isinstance(message, dict):
            return
        sender = message.get('username')
        call_id = message.get('call_id')
        action = message.get('action')
        if not isinstance(sender, str) or not isinstance(call_id, str):
            return
        if action == 'offer':
            if self.call_id is not None:
                self.send_signal(sender, call_id, 'reject')
                return False
            sdp = message.get('sdp')
            if (
                not isinstance(sdp, dict)
                or sdp.get('type') != 'offer'
                or not isinstance(sdp.get('sdp'), str)
            ):
                return False
            self.call_id = call_id
            self.peer = sender
            self.video = message.get('video') is True
            self.on_status(f'incoming:{sender}:{call_id}:{int(self.video)}', sender)
            return True
        if call_id == self.call_id and sender == self.peer:
            asyncio.run_coroutine_threadsafe(self._handle_signal(message), self.loop)

    async def _create_offer(self):
        try:
            await self._create_peer_connection()
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            self.send_signal(
                self.peer,
                self.call_id,
                'offer',
                {'type': self.pc.localDescription.type, 'sdp': self.pc.localDescription.sdp},
                video=self.video,
            )
        except Exception as exc:
            await self._close_call(f'Call setup failed: {exc}')

    async def accept_call(self):
        try:
            await self._create_peer_connection()
            message = self._pending_offer
            await self.pc.setRemoteDescription(
                RTCSessionDescription(sdp=message['sdp']['sdp'], type=message['sdp']['type'])
            )
            await self._attach_local_media()
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            self.send_signal(
                self.peer,
                self.call_id,
                'answer',
                {'type': self.pc.localDescription.type, 'sdp': self.pc.localDescription.sdp},
            )
            self.on_status(f'In call with {self.peer}', self.peer)
        except Exception as exc:
            await self._close_call(f'Call setup failed: {exc}')

    async def _create_peer_connection(self):
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

        @self.pc.on('track')
        def on_track(track):
            if track.kind == 'video':
                asyncio.create_task(self._receive_video(track))
            elif track.kind == 'audio':
                asyncio.create_task(self._receive_audio(track))

        self.audio_sender = self.pc.addTransceiver('audio', direction='sendrecv').sender
        if self.video:
            self.video_sender = self.pc.addTransceiver('video', direction='sendrecv').sender

    async def _attach_local_media(self):
        self.audio_sender.replaceTrack(_MicrophoneTrack())
        if self.video:
            self.video_sender.replaceTrack(_CameraTrack())

    async def _receive_video(self, track):
        try:
            while True:
                frame = await track.recv()
                image = frame.to_ndarray(format='rgb24')
                self.on_video_frame(image)
        except (MediaStreamError, asyncio.CancelledError):
            return
        except Exception as exc:
            self.on_status(f'Video receive failed: {exc}', self.peer)

    async def _receive_audio(self, track):
        output = None
        resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
        try:
            output = sd.OutputStream(samplerate=48000, channels=1, dtype='int16', blocksize=960)
            output.start()
            while True:
                frame = await track.recv()
                for converted in resampler.resample(frame):
                    samples = np.ascontiguousarray(converted.to_ndarray().T)
                    await asyncio.to_thread(output.write, samples)
        except (MediaStreamError, asyncio.CancelledError):
            return
        except Exception as exc:
            self.on_status(f'Audio playback failed: {exc}', self.peer)
        finally:
            if output is not None:
                output.stop()
                output.close()

    async def _handle_signal(self, message):
        action = message.get('action')
        if action == 'answer' and self.pc is not None:
            sdp = message.get('sdp')
            if (
                not isinstance(sdp, dict)
                or sdp.get('type') != 'answer'
                or not isinstance(sdp.get('sdp'), str)
            ):
                return
            try:
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=sdp['sdp'], type=sdp['type'])
                )
                if self.ring_timer is not None:
                    self.ring_timer.cancel()
                    self.ring_timer = None
                await self._attach_local_media()
                self.on_status(f'In call with {self.peer}', self.peer)
            except Exception as exc:
                self.on_status(f'Call setup failed: {exc}', self.peer)
                await self._close_call()
        elif action in ('reject', 'hangup'):
            result = 'rejected' if action == 'reject' else 'ended'
            await self._close_call(f'{self.peer} {result} the call.')

    def accept(self, message):
        self._pending_offer = message
        asyncio.run_coroutine_threadsafe(self.accept_call(), self.loop)

    def reject(self):
        if self.call_id is None:
            return
        self.send_signal(self.peer, self.call_id, 'reject')
        asyncio.run_coroutine_threadsafe(self._close_call(), self.loop)

    def end_call(self):
        if self.call_id is None:
            return
        self.send_signal(self.peer, self.call_id, 'hangup')
        asyncio.run_coroutine_threadsafe(self._close_call(), self.loop)

    async def _close_call(self, status='Call ended.'):
        if self.ring_timer is not None:
            self.ring_timer.cancel()
            self.ring_timer = None
        pc, self.pc = self.pc, None
        if pc is not None:
            for sender in pc.getSenders():
                if sender.track is not None:
                    sender.track.stop()
            await pc.close()
        self.call_id = None
        self.peer = None
        self.video = False
        self.on_status(status, None)

    def close(self, notify_peer=True):
        if notify_peer and self.call_id is not None:
            self.send_signal(self.peer, self.call_id, 'hangup')
        asyncio.run_coroutine_threadsafe(self._close_call(), self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
