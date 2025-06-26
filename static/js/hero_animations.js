// ==========================================
// ANIMACIONES HERO - EFECTO TYPEWRITER
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    
    // Función para crear efecto de máquina de escribir letra por letra
    function typewriterEffect(element, text, speed = 50) {
        return new Promise((resolve) => {
            if (!text || text.length === 0) {
                resolve();
                return;
            }
            
            element.innerHTML = '';
            element.style.opacity = '1';
            
            // Crear un cursor temporal
            const cursor = document.createElement('span');
            cursor.className = 'typewriter-cursor';
            cursor.innerHTML = '';
            element.appendChild(cursor);
            
            let i = 0;
            const timer = setInterval(() => {
                if (i < text.length) {
                    // Crear span para cada letra
                    const letter = document.createElement('span'); 
                    letter.textContent = text.charAt(i);
                    letter.style.animationDelay = '0s';
                    
                    // Insertar letra antes del cursor
                    element.insertBefore(letter, cursor);
                    i++;
                } else {
                    clearInterval(timer);
                    // Remover cursor después de un momento
                    setTimeout(() => {
                        if (cursor && cursor.parentNode) {
                            cursor.remove();
                        }
                        resolve();
                    }, 150);
                }
            }, speed);
        });
    }

    // Función para animar múltiples líneas de texto
    async function animateTitle(titleElement) {
        const originalHTML = titleElement.dataset.originalContent || titleElement.innerHTML;
        
        if (!titleElement.dataset.originalContent) {
            titleElement.dataset.originalContent = originalHTML;
        }
        
        // Separar las líneas por <br>
        const lines = originalHTML.split('<br>');
        
        // Crear contenedor para las líneas
        titleElement.innerHTML = '';
        
        for (let i = 0; i < lines.length; i++) {
            const lineDiv = document.createElement('div');
            lineDiv.className = `typewriter-line ${i > 0 ? 'second-line' : ''}`;
            titleElement.appendChild(lineDiv);
            
            let lineText = '';
            let hasSpan = false;
            
            // Procesar cada línea
            if (lines[i].includes('<span>') && lines[i].includes('</span>')) {
                const spanMatch = lines[i].match(/<span[^>]*>(.*?)<\/span>/);
                if (spanMatch) {
                    hasSpan = true;
                    lineText = spanMatch[1].trim();
                }
            } else {
                lineText = lines[i].replace(/<[^>]*>/g, '').trim();
                lineText = lineText.replace(/[\u200B-\u200D\uFEFF]/g, '');
            }
            
            // Escribir el texto letra por letra
            if (lineText && lineText.length > 0) {
                await typewriterEffect(lineDiv, lineText, 50);
                
                // Si tenía span, aplicar el estilo después de escribir
                if (hasSpan) {
                    lineDiv.innerHTML = `<span class="text-principal" style="color: #5D768B;">${lineText}</span>`;
                }
            }
            
            // Pausa entre líneas
            if (i < lines.length - 1) {
                await new Promise(resolve => setTimeout(resolve, 150));
            }
        }
    }
    
    // Función para iniciar las animaciones del hero
    async function startHeroAnimations() {
        const heroSection = document.querySelector('#Inicio');
        if (!heroSection) return;

        // Verificar si ya están activas las animaciones
        if (heroSection.classList.contains('animations-active')) {
            return;
        }

        heroSection.classList.add('animations-active');

        const heroTitle = heroSection.querySelector('h1');
        const heroDescription = heroSection.querySelector('p');
        const heroButtons = heroSection.querySelector('.flex.flex-col.sm\\:flex-row');
        const heroImage = heroSection.querySelector('img');
        const waves = heroSection.querySelectorAll('.wave');

        // Ocultar inicialmente todos los elementos excepto el título
        if (heroDescription) {
            heroDescription.style.opacity = '0';
            heroDescription.style.transform = 'translateY(30px)';
        }
        if (heroButtons) {
            heroButtons.style.opacity = '0';
            heroButtons.style.transform = 'translateY(20px)';
        }
        if (heroImage) {
            heroImage.style.opacity = '0';
            heroImage.style.transform = 'scale(0.8)';
        }

        // Animar el título primero
        if (heroTitle) {
            if (!heroTitle.dataset.originalContent) {
                heroTitle.dataset.originalContent = heroTitle.innerHTML;
            }
            
            await animateTitle(heroTitle);
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        // Animar otros elementos secuencialmente
        if (heroDescription) {
            heroDescription.classList.add('fade-in-up');
            await new Promise(resolve => setTimeout(resolve, 150));
        }

        if (heroButtons) {
            heroButtons.classList.add('slide-in-buttons');
        }

        if (heroImage) {
            heroImage.classList.add('scale-in-image');
        }

        // Animar las ondas del fondo
        waves.forEach((wave, index) => {
            wave.classList.add('wave-animation');
            if (index === 1) {
                wave.classList.add('wave2');
            }
        });
    }

    // Observador de intersección para activar animaciones
    const observerOptions = {
        threshold: 0.15,
        rootMargin: '0px 0px -50px 0px'
    };

    const heroObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !entry.target.classList.contains('animations-active')) {
                startHeroAnimations();
            }
        });
    }, observerOptions);

    // Observar la sección hero
    const heroSection = document.querySelector('#Inicio');
    if (heroSection) {
        const heroTitle = heroSection.querySelector('h1');
        if (heroTitle) {
            heroTitle.dataset.originalContent = heroTitle.innerHTML;
        }
        
        heroObserver.observe(heroSection);
        
        // Iniciar animaciones inmediatamente si la sección ya está visible
        const rect = heroSection.getBoundingClientRect();
        const isVisible = rect.top < window.innerHeight && rect.bottom > 0;
        
        if (isVisible) {
            setTimeout(() => {
                startHeroAnimations();
            }, 150);
        }
    }
});