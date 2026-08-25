// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef DARKOS_API_KEYS_PAGE_H
#define DARKOS_API_KEYS_PAGE_H

#include <QWidget>

class QLineEdit;

class ApiKeysPage final : public QWidget
{
public:
    explicit ApiKeysPage( QWidget* parent = nullptr );
    ~ApiKeysPage() override;

    QString openRouterKey() const;
    QString groqKey() const;
    bool hasAnyKey() const;
    void clearSecrets();

private:
    QLineEdit* m_openRouterKey;
    QLineEdit* m_groqKey;
};

#endif  // DARKOS_API_KEYS_PAGE_H
