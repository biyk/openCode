

def test_sounddevice_import():
    """Проверяет, что sounddevice установлен и может импортироваться."""
    import sounddevice
    assert sounddevice is not None


def test_sounddevice_query_devices():
    """Проверяет, что sounddevice может получить список устройств."""
    import sounddevice
    devices = sounddevice.query_devices()
    assert devices is not None
