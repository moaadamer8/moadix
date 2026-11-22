# The official PostgreSQL image (the gate's own pin, confinement.yaml images.postgres), run by the gate with a
# read-only root and only /tmp writable: the socket directory points at /tmp, and PGDATA is /tmp/pgdata (compose).
FROM docker.io/library/postgres:17-bookworm@sha256:40865bc877a289da75963d97d72b59633f639fc5af7a4e856bfa3714cae5b536
RUN rm -rf /var/run/postgresql && ln -s /tmp /var/run/postgresql
