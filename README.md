# EduSphere LMS



EduSphere LMS is a Django REST Framework-based Learning Management System backend.



## Project Structure



```text

EduSphere-LMS/

|-- backend/

|   |-- apps/

|   |   |-- accounts/

|   |   |-- academics/

|   |-- config/

|   |-- manage.py


|-- docs/

|   |-- api/

|   |-- architecture/

|   |-- database/

|-- frontend/

|-- .env.example

|-- requirements.txt

|-- README.md

```



## Technology Stack



- Python

- Django

- Django REST Framework

- PostgreSQL

- Psycopg

- python-dotenv



## Local Development Setup



### 1. Clone the repository



```bash

git clone <repository-url>

cd EduSphere-LMS

```



### 2. Create and activate a virtual environment



Windows CMD:



```cmd

py -m venv backend\\.venv

backend\\.venv\\Scripts\\activate

```



### 3. Install dependencies



```cmd

py -m pip install -r requirements.txt

```



### 4. Configure environment variables



Create the backend environment file:



```cmd

copy .env.example backend\\.env

```



Configure the values in `backend/.env`:



```env

SECRET_KEY=your-secret-key

DB_NAME=your-database-name

DB_USER=your-database-user

DB_PASSWORD=your-database-password

DB_HOST=your-database-host

DB_PORT=your-database-port

```



Generate a Django secret key:



```cmd

py -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

```



Use a PostgreSQL database configured with the credentials above.



**Never commit `backend/.env` or expose its secret values.**



### 5. Run database migrations



```cmd

cd backend

py manage.py migrate

```



### 6. Start the development server



```cmd

py manage.py runserver

```



Development server:



http://127.0.0.1:8000/



## API Routes



API base path:



`/api/academics/`



| Endpoint | Resource |

|---|---|

| `courses/` | Courses |

| `enrollment-requests/` | Enrollment requests |

| `course-invitations/` | Course invitations |

| `modules/` | Course modules |

| `lessons/` | Lessons |

| `payments/` | Payment obligations |

| `payment-attempts/` | Payment attempts |

| `payment-refunds/` | Payment refunds |



Django Admin:



`/admin/`



## Running Tests



From the `backend` directory:



```cmd

py manage.py test

```



Run deployment checks:



```cmd

py manage.py check --deploy

```



Note: Deployment checks may report security warnings with local development settings. Production requires separate security configuration.



## Current Development Status



- Django backend implemented.

- Accounts and academics applications configured.

- Course, enrollment, content and payment API resources registered.

- Frontend implementation is not yet present.

- Live payment gateway integration is not yet implemented.



## Security Notes



- Keep secret keys and database credentials in environment variables.

- Never commit `.env` files.

- Configure HTTPS, secure cookies, production `DEBUG`, `ALLOWED_HOSTS` and other deployment settings before production deployment.



