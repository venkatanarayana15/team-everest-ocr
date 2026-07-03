import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/upload': 'http://127.0.0.1:8000',
      '/status': 'http://127.0.0.1:8000',
      '/result': 'http://127.0.0.1:8000',
      '/pages': 'http://127.0.0.1:8000',
      '/jobs': 'http://127.0.0.1:8000',
      '/download': 'http://127.0.0.1:8000',
      '/correct': 'http://127.0.0.1:8000',
      '/retry': 'http://127.0.0.1:8000',
      '/metrics': 'http://127.0.0.1:8000',
      '/ping': 'http://127.0.0.1:8000',
      '/pdfs': 'http://127.0.0.1:8000',
      '/save-to-db': 'http://127.0.0.1:8000',
      '/tesseract-data': 'http://127.0.0.1:8000',
      '/upload-images': 'http://127.0.0.1:8000',
      '/upload-batch': 'http://127.0.0.1:8000',
      '/validate': 'http://127.0.0.1:8000',
      '/process-folder': 'http://127.0.0.1:8000',
      '/stream': 'http://127.0.0.1:8000',
      '/stream-batch': 'http://127.0.0.1:8000',
    },
  },
})
