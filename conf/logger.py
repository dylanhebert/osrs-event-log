import logging

# LOGGER STUFF
logger = logging.getLogger('REL')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',datefmt='%m/%d/%Y %I:%M:%S %p')
ch = logging.StreamHandler()
fh = logging.FileHandler('/home/pi/code_pi/osrseventlog/logs.log')
ch.setLevel(logging.DEBUG)
fh.setLevel(logging.INFO)
ch.setFormatter(formatter)
fh.setFormatter(formatter)
logger.addHandler(ch)
logger.addHandler(fh)