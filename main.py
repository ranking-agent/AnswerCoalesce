# from gunicorn.app.wsgiapp import WSGIApplication
#
# # --bind 0.0.0.0:6380 -w 1 -k uvicorn.workers.UvicornWorker -t 600 src.server:APP
# app = WSGIApplication()
# app.run()

import uvicorn

class App:
    ...

app = App()

if __name__ == "__main__":
    uvicorn.run("src.server:APP", host="127.0.0.1", port=5001, log_level="info")