import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Bootstrap is the only styling layer in this app, so its stylesheet is
// imported once here and every component uses Bootstrap class names.
import 'bootstrap/dist/css/bootstrap.min.css'
import './index.css'

import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)