/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./gravity/templates/**/*.html",
    "./accounts/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        'principal': '#5D768B',
        'principal-dark': '#4A5F73',
        'secundario': '#C8B39B',
        'fondo': '#F8EFE5',
        'blanco': '#FDFDFD',
        'gris-claro': '#f0f0f0ff',
        'gris-medio': '#6C757D',
        'gris-oscuro': '#495057',
        'exito': '#28A745',
        'error': '#DC3545',
        'advertencia': '#FFC107',
        'info': '#17A2B8',
      },
      fontFamily: {
        'cinzel': ['Cinzel', 'serif']
      },
      animation: {
        'fadeInUp': 'fadeInUp 0.3s ease-in-out',
        'float': 'float 3s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 2s ease-in-out infinite',
        'shimmer': 'shimmer 2s ease-in-out infinite',
        'slideInError': 'slideInError 0.4s ease-out',
        'slideInRight': 'slideInRight 0.5s ease-out',
        'fadeIn': 'fadeIn 0.6s ease-out',
        'slideInDown': 'slideInDown 0.6s ease-out',
        'slideInLeft': 'slideInLeft 0.6s ease-out',
        'successBounce': 'successBounce 1s ease-in-out',
        'errorShake': 'errorShake 0.5s ease-in-out',
        'iconPulse': 'iconPulse 2s ease-in-out infinite alternate',
        'adminGlow': 'adminGlow 2s ease-in-out infinite alternate',
        'confettiFall': 'confettiFall 3s linear forwards',
      },
      keyframes: {
        fadeInUp: {
          '0%': {
            transform: 'translateY(20px)',
            opacity: '0',
          },
          '100%': {
            transform: 'translateY(0)',
            opacity: '1',
          },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' }
        },
        'pulse-ring': {
          '0%': { transform: 'scale(1)', opacity: '0.3' },
          '50%': { transform: 'scale(1.1)', opacity: '0.1' },
          '100%': { transform: 'scale(1.2)', opacity: '0' }
        },
        shimmer: {
          '0%, 100%': { background: 'linear-gradient(90deg, #C8B39B, #5D768B)' },
          '50%': { background: 'linear-gradient(90deg, #5D768B, #C8B39B)' }
        },
        slideInError: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' }
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        slideInDown: {
          '0%': { opacity: '0', transform: 'translateY(-30px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        slideInLeft: {
          '0%': { opacity: '0', transform: 'translateX(-30px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' }
        },
        successBounce: {
          '0%, 20%, 50%, 80%, 100%': { transform: 'translateY(0)' },
          '40%': { transform: 'translateY(-10px)' },
          '60%': { transform: 'translateY(-5px)' }
        },
        errorShake: {
          '0%, 20%, 50%, 80%, 100%': { transform: 'translateX(0)' },
          '10%': { transform: 'translateX(-5px)' },
          '30%': { transform: 'translateX(5px)' },
          '60%': { transform: 'translateX(-3px)' },
          '90%': { transform: 'translateX(3px)' }
        },
        iconPulse: {
          '0%': { transform: 'scale(1)' },
          '100%': { transform: 'scale(1.1)' }
        },
        adminGlow: {
          '0%': { boxShadow: '0 0 5px rgba(255, 215, 0, 0.5)' },
          '100%': { boxShadow: '0 0 15px rgba(255, 215, 0, 0.8)' }
        },
        confettiFall: {
          '0%': { transform: 'translateY(-10px) rotate(0deg)', opacity: '1' },
          '100%': { transform: 'translateY(100vh) rotate(360deg)', opacity: '0' }
        }
      },
      boxShadow: {
        'auth': '0 20px 60px rgba(93, 118, 139, 0.12)',
        'auth-hover': '0 30px 80px rgba(93, 118, 139, 0.15)',
        'btn-primary': '0 4px 15px rgba(93, 118, 139, 0.3)',
        'btn-primary-hover': '0 8px 25px rgba(93, 118, 139, 0.4)',
        'card-hover': '0 8px 25px rgba(93, 118, 139, 0.15)',
        'profile': '0 10px 15px rgba(0, 0, 0, 0.1)',
        'wizard': '0 15px 35px rgba(93, 118, 139, 0.15)',
      },
      backdropBlur: {
        'xs': '2px',
      }
    },
  },
  plugins: [],
}