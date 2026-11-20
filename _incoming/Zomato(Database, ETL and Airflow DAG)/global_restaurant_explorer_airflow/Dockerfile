# Custom Apache Airflow 3.4.0 (Python 3.11) image for Global Restaurant Explorer ETL
# Extends the official Apache Airflow image with the ETL project's runtime dependencies
# pinned against the official Apache Airflow 3.4.0 / Python 3.11 constraints file.

FROM apache/airflow:3.4.0-python3.11

ARG AIRFLOW_VERSION=3.4.0
ARG PYTHON_VERSION=3.11
ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

USER airflow

COPY requirements-airflow.txt /tmp/requirements-airflow.txt

RUN pip install --no-cache-dir \
    -r /tmp/requirements-airflow.txt \
    --constraint "${CONSTRAINT_URL}"

ENV PYTHONPATH="/opt/airflow/etl_project:/opt/airflow/include:${PYTHONPATH}"
