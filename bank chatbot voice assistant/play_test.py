import sounddevice as sd
import soundfile as sf

audio, sample_rate = sf.read("cartesia_hbl_test.wav")

print("Playing Cartesia voice...")

sd.play(audio, sample_rate)
sd.wait()

print("Finished.")