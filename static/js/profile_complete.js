document.addEventListener('DOMContentLoaded', function() {
    let currentStep = 1;
    const totalSteps = 4;
    
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const submitBtn = document.getElementById('submitBtn');
    const lesionesCheckbox = document.getElementById('{{ form.tiene_lesiones.id_for_label }}');
    const lesionesContainer = document.getElementById('lesionesContainer');

    // Manejar checkbox de lesiones
    if (lesionesCheckbox) {
        lesionesCheckbox.addEventListener('change', function() {
            if (this.checked) {
                lesionesContainer.style.display = 'block';
            } else {
                lesionesContainer.style.display = 'none';
                document.getElementById('{{ form.descripcion_lesiones.id_for_label }}').value = '';
            }
        });
        
        // Verificar estado inicial
        if (lesionesCheckbox.checked) {
            lesionesContainer.style.display = 'block';
        }
    }

    function updateWizard() {
        // Actualizar pasos visuales
        document.querySelectorAll('.step').forEach((step, index) => {
            const stepNumber = index + 1;
            step.classList.remove('active', 'completed');
            
            if (stepNumber < currentStep) {
                step.classList.add('completed');
            } else if (stepNumber === currentStep) {
                step.classList.add('active');
            }
        });

        // Actualizar líneas de progreso
        document.querySelectorAll('.step-line').forEach((line, index) => {
            if (index + 1 < currentStep) {
                line.classList.add('completed');
            } else {
                line.classList.remove('completed');
            }
        });

        // Mostrar/ocultar contenido de pasos
        document.querySelectorAll('.step-content').forEach((content, index) => {
            const stepNumber = index + 1;
            if (stepNumber === currentStep) {
                content.classList.add('active');
            } else {
                content.classList.remove('active');
            }
        });

        // Actualizar botones de navegación
        prevBtn.style.display = currentStep === 1 ? 'none' : 'inline-flex';
        
        if (currentStep === totalSteps) {
            nextBtn.style.display = 'none';
            submitBtn.style.display = 'inline-flex';
        } else {
            nextBtn.style.display = 'inline-flex';
            submitBtn.style.display = 'none';
        }
    }

    function validateCurrentStep() {
        const currentStepContent = document.querySelector(`.step-content[data-step="${currentStep}"]`);
        const inputs = currentStepContent.querySelectorAll('input[required], select[required], textarea[required]');
        
        for (let input of inputs) {
            if (!input.value.trim()) {
                input.focus();
                return false;
            }
        }
        
        // Validación especial para lesiones
        if (currentStep === 2) {
            const lesionesCheckbox = document.getElementById('{{ form.tiene_lesiones.id_for_label }}');
            const descripcionLesiones = document.getElementById('{{ form.descripcion_lesiones.id_for_label }}');
            
            if (lesionesCheckbox && lesionesCheckbox.checked && !descripcionLesiones.value.trim()) {
                descripcionLesiones.focus();
                return false;
            }
        }
        
        return true;
    }

    // Event listeners para navegación
    nextBtn.addEventListener('click', function() {
        if (validateCurrentStep() && currentStep < totalSteps) {
            currentStep++;
            updateWizard();
        }
    });

    prevBtn.addEventListener('click', function() {
        if (currentStep > 1) {
            currentStep--;
            updateWizard();
        }
    });

    // Permitir navegación con teclado
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && e.target.type !== 'textarea') {
            e.preventDefault();
            if (currentStep < totalSteps && validateCurrentStep()) {
                nextBtn.click();
            } else if (currentStep === totalSteps) {
                submitBtn.click();
            }
        }
    });

    // Inicializar wizard
    updateWizard();
});