/**
 * Tuition Management System - Premium Frontend Engine
 * Core UI/UX Interactions & Client-side Validations
 */

document.addEventListener('DOMContentLoaded', function () {
    
    // === 1. Responsive Sidebar Toggle Layout ===
    const sidebar = document.querySelector('.sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const mainContent = document.querySelector('.main-content');

    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            sidebar.classList.toggle('active');
        });
        
        // Close sidebar when clicking outside on mobile devices
        document.addEventListener('click', function (e) {
            if (window.innerWidth <= 992 && sidebar.classList.contains('active')) {
                if (!sidebar.contains(e.target) && e.target !== sidebarToggle) {
                    sidebar.classList.remove('active');
                }
            }
        });
    }

    // === 2. Premium Theme Toggle Engine (Dark <-> Light) ===
    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const themeIcon = document.getElementById('themeIcon');
    const htmlElement = document.documentElement;

    // Load previously saved theme state or fallback to default 'dark'
    const savedTheme = localStorage.getItem('tms-theme') || 'dark';
    htmlElement.setAttribute('data-bs-theme', savedTheme);
    updateThemeIcon(savedTheme);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function () {
            const currentTheme = htmlElement.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            htmlElement.setAttribute('data-bs-theme', newTheme);
            localStorage.setItem('tms-theme', newTheme);
            updateThemeIcon(newTheme);
        });
    }

    function updateThemeIcon(theme) {
        if (!themeIcon) return;
        if (theme === 'dark') {
            themeIcon.className = 'fa-solid fa-sun';
        } else {
            themeIcon.className = 'fa-solid fa-moon';
        }
    }

    // === 3. Real-time Marks Validation Logic ===
    const totalMarksInput = document.getElementById('total_marks_input');
    const obtainedMarksInput = document.getElementById('obtained_marks_input');

    if (totalMarksInput && obtainedMarksInput) {
        const validateMarks = () => {
            const total = parseFloat(totalMarksInput.value) || 0;
            const obtained = parseFloat(obtainedMarksInput.value) || 0;

            if (obtained > total && total > 0) {
                obtainedMarksInput.setCustomValidity('Obtained marks cannot exceed total marks.');
                obtainedMarksInput.classList.add('is-invalid');
            } else {
                obtainedMarksInput.setCustomValidity('');
                obtainedMarksInput.classList.remove('is-invalid');
            }
        };

        totalMarksInput.addEventListener('input', validateMarks);
        obtainedMarksInput.addEventListener('input', validateMarks);
    }

    // === 4. Auto-Dismiss Alert Banners ===
    const alerts = document.querySelectorAll('.custom-alert');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 4000); // Automatically fades out after 4 seconds
    });
});