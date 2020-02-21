[![Build Status](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce.svg?branch=master)](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce)

# AnswerCoalesce

A Swagger UI/web service interface for the Answer Coalesce service.

A service that accepts a properly formatted Robokop-like answer and returns a set of coalesced answers to the user.

## Deployment

Please download and implement the Docker container located in the Docker hub repo: renciorg\ac. 

Kubernetes deployment files are available in the \kubernetes directory.

### Local environment

Note: This environment expects Python version 3.8.

Install required packages: pip install -r requirements.txt

Run: main.py

### Docker

```bash
cd <code base>
docker-compose build
docker-compose up -d
```
## Usage

http://"host name or IP":"port"/apidocs
