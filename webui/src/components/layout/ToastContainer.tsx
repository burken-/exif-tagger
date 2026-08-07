import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType, duration?: number) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = 'info', duration = 4000) => {
      const id = Math.random().toString(36).substring(2, 9);
      const newToast: Toast = { id, message, type };
      setToasts((prev) => [...prev, newToast]);

      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
    },
    [removeToast]
  );

  return (
    <ToastContext.Provider value={{ showToast, removeToast }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full px-4 pointer-events-none">
      {toasts.map((toast) => {
        const getToastStyles = (type: ToastType) => {
          switch (type) {
            case 'success':
              return {
                border: 'border-emerald-500/40 bg-emerald-950/90 text-emerald-100',
                icon: CheckCircle2,
                iconColor: 'text-emerald-400',
              };
            case 'error':
              return {
                border: 'border-rose-500/40 bg-rose-950/90 text-rose-100',
                icon: AlertCircle,
                iconColor: 'text-rose-400',
              };
            case 'warning':
              return {
                border: 'border-amber-500/40 bg-amber-950/90 text-amber-100',
                icon: AlertTriangle,
                iconColor: 'text-amber-400',
              };
            case 'info':
            default:
              return {
                border: 'border-indigo-500/40 bg-indigo-950/90 text-indigo-100',
                icon: Info,
                iconColor: 'text-indigo-400',
              };
          }
        };

        const style = getToastStyles(toast.type);
        const IconComponent = style.icon;

        return (
          <div
            key={toast.id}
            className={cn(
              'pointer-events-auto flex items-start gap-3 p-3.5 rounded-lg border shadow-lg backdrop-blur-md transition-all duration-300 animate-in slide-in-from-bottom-5',
              style.border
            )}
          >
            <IconComponent className={cn('w-5 h-5 shrink-0 mt-0.5', style.iconColor)} />
            <p className="text-sm font-medium flex-1 break-words leading-snug">{toast.message}</p>
            <button
              onClick={() => onDismiss(toast.id)}
              className="text-slate-400 hover:text-white transition-colors p-0.5 rounded cursor-pointer"
              aria-label="Dismiss toast"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};

export default ToastContainer;
