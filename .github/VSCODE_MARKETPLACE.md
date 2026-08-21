# VS Code Marketplace publishing

Stable TAPL tags publish `paragonnov.tapl-workflow-viewer` automatically after
the release job has built and validated its VSIX. Alpha, beta, and release
candidate tags keep publishing their VSIX through GitHub Releases, but skip the
Marketplace job.

The workflow uses GitHub OIDC and Microsoft Entra ID. It does not store a
Marketplace Personal Access Token.

## One-time setup

1. Create or select a Microsoft Entra application/service principal or a
   user-assigned managed identity that `azure/login` can use.
2. Add a GitHub federated credential with:
   - issuer: `https://token.actions.githubusercontent.com`
   - audience: `api://AzureADTokenExchange`
   - subject: `repo:qkdxorjs1002/tapl:environment:vscode-marketplace`
3. Create the `vscode-marketplace` GitHub environment. Restrict its deployment
   branches and tags to trusted release refs, and store these environment
   secrets:
   - `AZURE_CLIENT_ID`
   - `AZURE_TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID`
4. Add the Entra identity to the Visual Studio Marketplace publisher
   `paragonnov` with the **Contributor** role. Follow Microsoft's secure
   automated publishing procedure to resolve the identity's Azure DevOps
   profile/resource ID.

Official references:

- [Secure automated publishing to Visual Studio Marketplace](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#secure-automated-publishing-to-visual-studio-marketplace)
- [GitHub OIDC authentication to Azure](https://docs.github.com/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-azure)

## Release behavior

- Stable tag such as `2.0.1`: publish the validated VSIX with
  `vsce publish --azure-credential`.
- Prerelease tag such as `2.0.1-beta4`: skip Marketplace publishing.
- Re-running a stable tag is safe: `--skip-duplicate` treats an existing
  Marketplace version as successful.

If the stable Marketplace job reports that it cannot acquire an Entra token,
verify the GitHub environment name, federated credential subject, and three
Azure environment secrets. A `401` or `403` after login usually means the
identity is not a Contributor of the `paragonnov` Marketplace publisher.
