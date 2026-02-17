apiVersion: v1
kind: Service
metadata:
  name: {{ include "helm-scaffold-example.fullname" . }}
  labels:
    {{- include "helm-scaffold-example.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "helm-scaffold-example.selectorLabels" . | nindent 4 }}
