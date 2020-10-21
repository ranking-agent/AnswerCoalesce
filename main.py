from gunicorn.app.wsgiapp import WSGIApplication

# --bind 0.0.0.0:6380 -w 1 -k uvicorn.workers.UvicornWorker -t 600 src.server:APP
app = WSGIApplication()
app.run()
