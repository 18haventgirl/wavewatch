"""Start upstream with the Windows/system trust store; no TLS bypass."""
import truststore
truststore.inject_into_ssl()
import changedetectionio
if __name__=='__main__':
    changedetectionio.main()
