FROM mcr.microsoft.com/azure-cli:2.88.0

ENV HOME=/home/app \
    AZURE_CONFIG_DIR=/home/app/.azure \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8012

WORKDIR /app

RUN az bicep install \
    && chown -R 10001:0 /home/app \
    && chmod -R g=u /home/app

COPY --chown=10001:0 server.py azure_iac.py sketches.json container-entrypoint.sh ./
COPY --chown=10001:0 static ./static

RUN chmod 0555 /app/container-entrypoint.sh

USER 10001
EXPOSE 8012

ENTRYPOINT ["/app/container-entrypoint.sh"]
