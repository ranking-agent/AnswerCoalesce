[![Build Status](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce.svg?branch=master)](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce)

# AnswerCoalesce
### A web service and Swagger UI for the Answer Coalesce service for ARAGORN.

This serivce accepts a [translator reasoner standard message](https://github.com/NCATS-Tangerine/NCATS-ReasonerStdAPI) containing answers and returns the same format with answers that have been coalesced.

## Demonstration

A live version of the API can be found [here](https://answercoalesce.renci.org/apidocs/).

An example notebook demonstrating the API can be found [here](https://github.com/TranslatorIIPrototypes/AnswerCoalesce/blob/master/documentation/AnswerCoalescence.ipynb).

## Deployment

Please download and implement the Docker container located in the Docker hub repo: renciorg\ac.

Kubernetes deployment files are available in the \kubernetes directory.

### Local Deployment

This environment expects Python version 3.8.

```bash
cd <code base>
pip install -r requirements.txt
python main.py
```

### Docker

```bash
cd <code base>
docker-compose build
docker-compose up -d
```

## Usage

http://"host name or IP":"port"/apidocs
