/**
 * BBMS JavaScript Utilities
 */
document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss alert messages after 5 seconds
  const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
  alerts.forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) {
        bsAlert.close();
      }
    }, 5000);
  });
});
