> TODO a proper README
# SWIPE
Project description

## Non-exclusive list of envs required to start the service
s3 storage settings

- STORAGE_ACCESS_KEY
- STORAGE_SECRET_KEY
- STORAGE_ENDPOINT
- STORAGE_REGION

sentry settings
- SENTRY_SWIPE_SERVER_URL
- SENTRY_MATCHMAKER_URL
- SENTRY_MATCHMAKING_SERVER_URL
- SENTRY_CHAT_SERVER_URL

other settings

- DATABASE_URL
- REDIS_URL


- SWIPE_REST_SERVER_HOST
- SWIPE_LOGGING_LEVEL
- SWIPE_BLACKLIST_ENABLED
- SWIPE_SECRET_KEY
- SWIPE_PORT


- MATCHMAKING_DEBUG_MODE=True
- MATCHMAKING_BLACKLIST_ENABLED=True
- MATCHMAKING_ROUND_LENGTH_SECS=5

## Preparing the VM for deployment
### install docker
```
#!/bin/bash
set -x
set -e
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io
sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
sudo groupadd docker
```
### setup yandex cloud client
https://cloud.yandex.ru/docs/cli/operations/profile/profile-create#create
```
curl https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
source ~/.bashrc
yc init
yc config set token $YC_OAUTH_TOKEN
yc config profile get default
yc iam service-account --folder-id $YC_FOLDER_ID list
yc iam key create --service-account-name storage-and-docker-admin --output key.json                    
yc config set service-account-key key.json
yc config set cloud-id $YC_CLOUD_ID
yc config set folder-id $YC_FOLDER_ID
yc container registry configure-docker
```

### run
Unsurprisingly
```
docker-compose -f docker-compose.yml up -d
```
