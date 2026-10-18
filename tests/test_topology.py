from pathlib import Path
import yaml

def test_no_plc_or_gateway_published_ports():
    for filename in ['compose.yaml', 'compose.edge.yaml']:
        compose = yaml.safe_load(Path(filename).read_text())
        assert compose['networks']['plc']['internal']
        for service in ['gateway', 'simulator']:
            assert 'ports' not in compose['services'][service]
        assert compose['services']['simulator']['networks'] == ['plc']
    compose = yaml.safe_load(Path('compose.yaml').read_text())
    assert compose['services']['proxy']['ports'] == ['127.0.0.1:8443:443']
    assert 'ports' not in compose['services']['relay']
