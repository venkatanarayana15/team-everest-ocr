import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/upload': 'http://localhost:8000',
      '/status': 'http://localhost:8000',
      '/result': 'http://localhost:8000',
      '/pages': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/download': 'http://localhost:8000',
      '/correct': 'http://localhost:8000',
      '/retry': 'http://localhost:8000',
      '/metrics': 'http://localhost:8000',
      '/ping': 'http://localhost:8000',
      '/pdfs': 'http://localhost:8000',
      '/save-to-db': 'http://localhost:8000',
      '/tesseract-data': 'http://localhost:8000',
      '/upload-images': 'http://localhost:8000',
      '/upload-batch': 'http://localhost:8000',
      '/validate': 'http://localhost:8000',
      '/process-folder': 'http://localhost:8000',
    },
  },
})
