"""Configure a dedicated pinned upstream store before its HTTP service starts."""
import os
from pathlib import Path
import sys


def main():
    try:
        import truststore
    except ImportError:
        # Upstream Linux images may use their standard verified CA bundle.
        # No certificate verification is disabled in either path.
        pass
    else:
        truststore.inject_into_ssl()
    from changedetectionio.store import ChangeDetectionStore
    import changedetectionio
    root = Path(__file__).resolve().parents[1]
    path = Path(os.environ['OBS_ENGINE_DATA']).resolve()
    if path == (root / 'data' / 'engine').resolve():
        raise RuntimeError('The V2 engine must not use the legacy engine directory')
    key = os.environ.get('OBS_ENGINE_KEY', '')
    if len(key) < 32:
        raise RuntimeError('Set a dedicated random engine key of at least 32 characters')
    path.mkdir(parents=True, exist_ok=True)
    store = ChangeDetectionStore(datastore_path=str(path), include_default_watches=False, version_tag='0.70.4')
    store.data['settings']['application']['api_access_token_enabled'] = True
    store.data['settings']['application']['api_access_token'] = key
    store.commit()
    del store
    sys.argv = [sys.argv[0], '-d', str(path), '-h', os.environ.get('OBS_ENGINE_HOST', '127.0.0.1'),
                '-p', os.environ.get('OBS_ENGINE_PORT', '8851'), '-C']
    changedetectionio.main()


if __name__ == '__main__':
    main()
