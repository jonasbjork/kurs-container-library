<?php
$cfg['blowfish_secret'] = file_get_contents('/tmp/kurs-phpmyadmin-secret');
$cfg['Servers'][1]['auth_type'] = 'cookie';
$cfg['Servers'][1]['host'] = getenv('PMA_HOST');
$cfg['Servers'][1]['port'] = getenv('PMA_PORT') ?: '3306';
$cfg['Servers'][1]['AllowNoPassword'] = false;
$cfg['TempDir'] = '/opt/app-root/src/tmp';
